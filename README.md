# Watermark-Tracer-and-Remover

课程小项目。使用了一个基于 yolov5 的可视水印检测项目（见下文 Watermark-Tracer 标题）和论文 _LaMa Image Inpainting, Resolution-robust Large Mask Inpainting with Fourier Convolutions, WACV 2022_ 中算法的一个打包项目

（本 README 在第一个项目的 README 上写就）

[YOLOv5 Watermark Tracer](https://github.com/Kamino666/watermark-tracer)

[(Original) LaMa](https://github.com/advimman/lama)

[LaMa on Modelscope](https://www.modelscope.cn/models/iic/cv_fft_inpainting_lama/summary)

项目中含有YOLOv5已经训练好的模型，但不含有LaMa模型。

效果图没找到看起来比较稳的图床随作罢

## 环境配置和运行

### 环境

建议使用 Anaconda

克隆本项目后：

```
cd watermark-tracer-and-remover
conda env create -f wm_trace_and_remove.yaml
```

或者使用 pip

```
在此之前，应当创建一个基于python3.8的虚拟环境。
pip instal -r requirements.txt
```

注意，本项目为了能正常上传至git，不包含LaMa模型的部分。因此需要您自行参照 [LaMa on Modelscope](https://www.modelscope.cn/models/iic/cv_fft_inpainting_lama/summary) 配置LaMa模型。

模型必须下载到项目下名为lama_modelscope的文件夹
```
modelscope download --model iic/cv_fft_inpainting_lama README.md --local_dir ./lama_modelscope
```

### 运行

注意，请切换到本项目的环境。

```
conda activate wm_trace

python trace_and_remove.py -m （文件名）
```

程序会提示是否检测到水印，也会提示文件存放在何处和文件的名字。

运行时，还会额外生成一张图片，是用于 LaMa 模型输入的水印掩码图片。名为`(输入文件名)_temp_mask.png`。