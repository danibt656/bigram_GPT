# bigram Generatively Pretrained Transformer

![GitHub code size in bytes](https://img.shields.io/github/languages/code-size/danibt656/bigram_GPT?style=flat-square)
![GitHub commit activity](https://img.shields.io/github/commit-activity/y/danibt656/bigram_GPT?style=flat-square)

> Author: Daniel Barahona, 2023

An implementation of GPT: the Generatively Pretrained Transformer, just to learn how it works. Its architecture is the following:

<img src="transformer.png" alt="Transformer scheme" width="500"/>

GPT uses the concepts of "self-attention" and residual blocks to learn to predict "tokens" (which in this example are just characters) based on a chunk of previous tokens. For example, after the chunk "Shakespear", it should learn that it is highly probable that the next token will be "e".

To run the script:

```
python tinyGPT.py -f input.txt -i 5000
```

Where `-f` is the file with the training contents, and `-i` is the number of training iterations to perform.

***

Original sources:

Vaswani, A., Shazeer, N., Parmar, N., Uszkoreit, J., Jones, L., Gomez, A.N., Kaiser, Ł. and Polosukhin, I., 2017. *Attention is all you need*. Advances in neural information processing systems, 30.

He, K., Zhang, X., Ren, S. and Sun, J., 2016. *Deep residual learning for image recognition*. In Proceedings of the IEEE conference on computer vision and pattern recognition (pp. 770-778).