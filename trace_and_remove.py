from email.mime import image
import logging
import random
import tkinter as tk
import tkinter.filedialog
from pathlib import Path
import argparse
import sys
from unittest import result

import cv2
import matplotlib
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

import skimage.draw as draw

import torch
from PIL import Image, ImageTk

# 对视频的功能，本来不想删，但是mmcv这个库实在是有点难绷，所以想了想还是花点劲删了视频相关的所有功能算了
# from mmcv import VideoReader

# 原溯源功能，使用百度API
# from baidu import BaiduAPI

# My Code
from modelscope.outputs import OutputKeys
from modelscope.pipelines import pipeline
from modelscope.utils.constant import Tasks

# 配置logger
logger = logging.getLogger("watermark-tracer")
plt.rcParams["font.family"] = "SimHei"

# 视频相关，不启用，避免要装mmcv
# def detect_watermark_from_video_result(frames, res, threshold=0.1):
#     res: pd.DataFrame = res.sort_values(by="confidence", ascending=False)
#     frames_np = [np.array(i) for i in frames]
#     # 提取最高置信度
#     res = res[res["confidence"] > threshold]
#     print("检测结果：\n", res)
#     w1, h1, w2, h2 = [int(i) for i in res.loc[0].to_list()[:4]]
#     wms = [i[h1:h2, w1:w2] for i in frames_np]  # watermarks
#     # 增强水印
#     wm = estimate_watermark_from_images(wms)
#     return wm, [
#         (w1, h1, w2, h2),
#     ]


def detect_watermark_from_img_result(img, res, err_ratio=0.05, threshold=0.1):
    res: pd.DataFrame = res.sort_values(by="confidence", ascending=False)
    img_np = np.array(img)
    # 以最高置信度为主，假如有其他大小相当的检测框则合并
    width, height = None, None
    for i, box in res.iterrows():
        w, h = box["xmax"] - box["xmin"], box["ymax"] - box["ymin"]
        if width is None:  # first run
            width, height = w, h
            continue
        if (
            w > width * (1 + err_ratio)
            or w < width * (1 - err_ratio)
            or h > height * (1 + err_ratio)
            or h < height * (1 - err_ratio)
        ):
            res.loc[i, "class"] = 1
        if box["confidence"] < threshold:
            res.loc[i, "class"] = 1
    res_less = res.drop(index=res[res["class"] == 1].index)
    print("检测结果：\n", res)
    boxes = [list(map(int, i[1:5])) for i in res_less.itertuples()]
    # 假如少于等于5个，直接返回，否则根据多幅图像提取水印
    if len(res) <= 5:
        print("未使用增强")
        # w1, h1, w2, h2 = boxes[0]
        w1, h1, w2, h2 = random.choice(boxes)
        return img_np[h1:h2, w1:w2], boxes
    else:
        print("增强")
        # 把所有子图都resize到相同大小
        wms = []  # watermarks
        for w1, h1, w2, h2 in boxes:
            i = img_np[h1:h2, w1:w2]
            i = Image.fromarray(i).resize((int(width), int(height)))
            wms.append(np.array(i))
        # 增强水印
        wm = estimate_watermark_from_images(wms)
        return wm, [list(map(int, i[1:5])) for i in res.itertuples()]


def estimate_watermark_from_images(imgs: list, enhance: int = 50):
    # 估计水印
    grad_x = list(map(lambda x: cv2.Sobel(x, cv2.CV_64F, 1, 0, ksize=3), imgs))
    grad_y = list(map(lambda x: cv2.Sobel(x, cv2.CV_64F, 0, 1, ksize=3), imgs))
    Wm_x = np.median(np.array(grad_x), axis=0)
    Wm_y = np.median(np.array(grad_y), axis=0)

    # plt.subplot(311)  # DEBUG
    # plt.imshow(np.abs(Wm_x ** 2 + Wm_y ** 2) / np.max(Wm_x ** 2 + Wm_y ** 2))  # DEBUG
    # ax = plt.gca()
    # ax.axes.xaxis.set_visible(False)
    # ax.axes.yaxis.set_visible(False)

    est = poisson_reconstruct(Wm_x, Wm_y)
    # 转换成255的
    est: np.ndarray = 255 * (est - np.min(est)) / (np.max(est) - np.min(est))
    est = est.astype(np.uint8)
    # DEBUG
    # plt.subplot(312)  # DEBUG
    # plt.imshow(est)  # DEBUG
    # ax = plt.gca()
    # ax.axes.xaxis.set_visible(False)
    # ax.axes.yaxis.set_visible(False)

    # 寻找增强区域的模版
    channels = []
    for i in range(est.shape[-1]):
        # 二值化
        blur = cv2.GaussianBlur(est[:, :, i], (5, 5), 0)
        ret, th = cv2.threshold(blur, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        channels.append(th)
    mask = np.zeros_like(channels[0]).astype(bool)
    for c in channels:
        mask = mask | c.astype(bool)
    mask = mask[:, :, np.newaxis].repeat(3, axis=2)
    # print(mask.shape, est.shape)
    # print(mask.dtype, est.dtype)
    # plt.figure(2)
    # plt.subplot(211)
    # plt.imshow(mask.astype(int)*255)
    # plt.subplot(212)
    # plt.imshow(est)
    # plt.show()
    # 增强
    est = est + enhance * mask
    est: np.ndarray = 255 * (est - np.min(est)) / (np.max(est) - np.min(est))
    est = est.astype(np.uint8)
    # DEBUG
    # plt.subplot(313)
    # plt.imshow(est)
    # ax = plt.gca()
    # ax.axes.xaxis.set_visible(False)
    # ax.axes.yaxis.set_visible(False)
    # plt.show()
    return est


def poisson_reconstruct(
    gradx,
    grady,
    kernel_size=3,
    num_iters=100,
    h=0.1,
    boundary_image=None,
    boundary_zero=True,
):
    """
    Iterative algorithm for Poisson reconstruction.
    Given the gradx and grady values, find laplacian, and solve for images
    Also return the squared difference of every step.
    h = convergence rate
    """
    fxx = cv2.Sobel(gradx, cv2.CV_64F, 1, 0, ksize=kernel_size)
    fyy = cv2.Sobel(grady, cv2.CV_64F, 0, 1, ksize=kernel_size)
    laplacian = fxx + fyy
    m, n, p = laplacian.shape

    if boundary_zero is True:
        est = np.zeros(laplacian.shape)
    else:
        assert boundary_image is not None
        assert boundary_image.shape == laplacian.shape
        est = boundary_image.copy()

    est[1:-1, 1:-1, :] = np.random.random((m - 2, n - 2, p))
    loss = []

    for i in range(num_iters):
        old_est = est.copy()
        est[1:-1, 1:-1, :] = 0.25 * (
            est[0:-2, 1:-1, :]
            + est[1:-1, 0:-2, :]
            + est[2:, 1:-1, :]
            + est[1:-1, 2:, :]
            - h * h * laplacian[1:-1, 1:-1, :]
        )
        error = np.sum(np.square(est - old_est))
        loss.append(error)
    return est


if __name__ == "__main__":
    # 选择输入
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "-m",
        "--image",
        required=False,
        type=str,
        help="输入图片路径，如没有则调用对话框进行选择",
    )
    parser.add_argument("--no_tk", action="store_true", help="是否使用tkinter，一般不需要带此参数")
    parser.add_argument("-s","--show",action="store_true",help="是否展示水印检测的结果")
    
    # 百度API溯源用的参数，不需要了，所以就删掉了
    # parser.add_argument("--no_api", action="store_true", help="是否使用百度API")
    
    args = parser.parse_args()
    if args.image is not None:
        file_path = args.image
    else:
        # GUI选择图片
        root = tk.Tk()
        file_path = tkinter.filedialog.askopenfilename(
            multiple=False,
            filetypes=[("图片", ".jpg"), ("图片", ".png")],
        )
        root.destroy()
    file_path = Path(file_path)
    if file_path.is_file() is False:
        logger.error("未选择资源")
        sys.exit()

    # 提取
    if file_path.suffix in [".jpg", ".png", ".jpeg"]:  # 图片
        file_type = "image"
        imgs = [Image.open(file_path).convert("RGB")]
    else:  # 视频（平均抽取10帧）
        # 此功能已经弃用
        # file_type = "video"
        # video = VideoReader(str(file_path))
        # indices = np.linspace(2, video.frame_cnt - 2, 10).astype(int)
        # imgs = [Image.fromarray(video.get_frame(i)[:, :, ::-1]) for i in indices]
        logger.error("不支持视频文件")
        sys.exit()

    # 加载模型
    logger.info("开始加载YoloV5模型")
    model = torch.hub.load("yolov5", "custom", path="yolov5/best.pt", source="local")
    model = model.cpu()
    matplotlib.use("Qt5Agg")
    logger.info("YoloV5加载成功")

    # 检测
    logger.info("检测中")
    results = model(imgs)

    # 提取水印
    results = results.pandas().xyxy
    if file_type == "image":
        if len(results[0]) == 0:
            logger.error("Yolo检测失败")
            sys.exit()
        test_wm, box = detect_watermark_from_img_result(imgs[0], results[0])
    elif file_type == "video":
        logger.error("不支持视频文件")
        sys.exit()
        # idx = -1
        # for i, result_item in enumerate(results):
        #     if len(result_item) != 0:
        #         idx = i
        #         break
        # if idx == -1:
        #     logger.error("Yolo检测失败")
        #     print(results)
        #     sys.exit()
        # test_wm, box = detect_watermark_from_video_result(imgs, results[idx])
    else:
        raise ValueError

    # My Code
    # 掩码
    img_for_cv=cv2.imread(file_path)
    print(f"图像尺寸: {img_for_cv.shape}")
    height, width = img_for_cv.shape[:2]
    print(f"高度: {height}, 宽度: {width}")
    # 创建与图像大小相同的掩码
    mask = np.zeros(img_for_cv.shape[:2], dtype=np.uint8)
    
    # print(f"掩码范围: [{start_row}:{end_row}, {start_col}:{end_col}]")
    # 这个是反过来的，之前得的那个是xy，这个是yx，1000（横向长度）是写在后面的
    # opencv真是独特呢
    mask[int(results[0]['ymin'][0]):int(results[0]['ymax'][0]), int(results[0]['xmin'][0]):int(results[0]['xmax'][0])] = 255
    # mask[40:152, 1911:2096] = 255
    
    # 应用掩码
    mask_result = cv2.bitwise_and(img_for_cv, img_for_cv, mask=mask)
    
    cv2.imwrite(f"{file_path.stem}_temp_mask.png",mask)
    
    # # TEST 显示原图和掩码结果
    # cv2.namedWindow("Masked img",cv2.WINDOW_NORMAL)
    # cv2.namedWindow("Original img",cv2.WINDOW_NORMAL)
    # cv2.imshow("Masked img", mask_result)
    # cv2.imshow("Original img", img_for_cv)
    # cv2.destroyAllWindows()

    # 重绘水印区域
    print(file_path)
    # print(f"simple_lama '{file_path}' temp_mask.jpg -o {file_path.stem}_lama_out.jpg")
    # os.system(f'simple_lama "{file_path}" temp_mask.jpg -o {file_path.stem}_lama_out.jpg')
    # 加载Lama模块
    input_location = file_path.__str__()
    input_mask_location = f"{file_path.stem}_temp_mask.png" 
    input = {
            'img':input_location,
            'mask':input_mask_location,
    }

    logger.info("开始加载Lama")
    inpainting = pipeline(Tasks.image_inpainting, model='./lama_modelscope')
    logger.info("正在重绘水印区域")
    result = inpainting(input)
    logger.info("重绘完成")
    logger.info(f"结果已经保存到当前目录下的{file_path.stem}_lama_result.png")
    vis_img = result[OutputKeys.OUTPUT_IMG]
    cv2.imwrite(f'{file_path.stem}_lama_result.png', vis_img)


# 溯源功能已经删除。
# 溯源
# if args.no_api is False:
#     try:
#         api = BaiduAPI('baidu_cfg.json')
#         # 获取百度API的结果
#         mark_res = api.detect_mark(Image.fromarray(test_wm))
#         ocr_res = api.detect_text(Image.fromarray(test_wm))
#         ocr_words: str = ocr_res['words_result'][0]['words'] if ocr_res['words_result_num'] >= 1 else None
#         # if '@' in ocr_words:
#         #     ocr_words = ocr_words[ocr_words.index('@'):]
#         # 依据逻辑判断
#         if mark_res['result_num'] > 0 and mark_res['result'][0]['probability'] >= 0.7:  # logo识别成功
#             if ocr_res['words_result_num'] >= 1:  # OCR成功
#                 search_res = api.search(ocr_words)
#             else:  # OCR失败
#                 search_res = api.search(mark_res['result'][0]['name'])
#             output = f"检测到可能的水印来源：{mark_res['result'][0]['name']}\n" + \
#                      f"以下是详细信息：\n{search_res[0]['title']} \n{search_res[0]['href']} \n{search_res[0]['summary']}\n" + \
#                      "获取方式：百度Logo识别+搜索引擎"
#         elif ocr_res['words_result_num'] >= 1:  # OCR成功
#             search_res = api.search(ocr_words)
#             output = f"检测到可能的水印来源：{ocr_words}\n" + \
#                      f"以下是详细信息：\n{search_res[0]['title']} \n{search_res[0]['href']} \n{search_res[0]['summary']}\n" + \
#                      "获取方式：百度OCR+搜索引擎"
#         else:  # logo和OCR都失败
#             output = "溯源失败"
#     except Exception:
#         output = "API调用错误"
# else:
#     output = "API调用错误"
# print(output)

# 展示功能，已经用原始的OpenCV代替
# 展示
if 'args' in locals() and args.show is True:
    new_img = np.array(imgs[0])
    for point in box:
        rr, cc = draw.rectangle_perimeter(point[:2], end=point[2:], shape=imgs[0].size)
        new_img[cc, rr] = (0, 255, 255)
    new_img = Image.fromarray(new_img)

    if args.no_tk is False:
        root = tk.Tk()  # 创建一个Tkinter.Tk()实例
        frame_l = tk.Frame(master=root, relief=tk.RAISED, borderwidth=1)
        frame_l.grid(row=0, column=0)
        _new_img = new_img.resize((int(new_img.width / new_img.height * 400), 400))
        _source_photo = ImageTk.PhotoImage(_new_img)
        label1 = tk.Label(master=frame_l, image=_source_photo)
        label1.pack()

        frame_r = tk.Frame(master=root, relief=tk.RAISED, borderwidth=1)
        frame_r.grid(row=0, column=1)
        _test_wm = Image.fromarray(test_wm)
        _photo = ImageTk.PhotoImage(_test_wm)
        label2 = tk.Label(master=frame_r, image=_photo, bg='gray')
        label2.grid(row=0, column=0)
        # 这个text本来是用来显示溯源结果的，也就是上面注释掉的代码里的output，不过都删掉了，我就改成水印了
        label3 = tk.Label(master=frame_r, text="水印", justify=tk.LEFT, wraplength=300)  # , width=30
        label3.grid(row=1, column=0)
        # 添加confidence值显示
        label4 = tk.Label(master=frame_r, text=f"置信度: {results[0]['confidence'][0]:.4f}", justify=tk.LEFT, wraplength=300)
        label4.grid(row=2, column=0)
        root.mainloop()
    else:
        plt.figure(1)
        plt.subplot(121)
        plt.imshow(new_img)
        plt.subplot(122)
        plt.imshow(test_wm)
        plt.show()
else:
    sys.exit()