# 编译合并核心

运行时仍使用 vendor/python 内置的 macOS arm64 CPython 3.12，不依赖用户系统 Python。
构建时另外需要有开发头文件的 macOS arm64 CPython 3.12（本次构建解释器 3.12.13，运行解释器 3.12.14），创建隔离环境：

```sh
/path/to/python3.12 -m venv .build/cython-tools
.build/cython-tools/bin/python -m pip install -r scripts/merge-compiler-requirements.txt
vendor/python/bin/python3.12 scripts/build-merge-engine.py
```

scripts/build-app.sh 自动调用编译，拷贝三个扩展及对应 Python 源码，再用安装包内置解释器验证加载的是 .so。
编译器固定 Cython 3.2.4 / setuptools 80.9.0，使用 -O3，不开启 fast-math、关闭边界检查或不安全数值转换选项。
依赖由构建环境安装，运行时不会联网安装或临时编译。

编译模块为 workbook_dom、workbook_cells、workbook_history。可通过不含 .so 的源码目录运行参考实现；正式包强制验证编译核心已加载，不静默退回源码并声称启用了加速。
生成目录 .build/merge-engine 保存同源源码、C 源码、性能注释 HTML、扩展和来源清单。正式包的缓存键和候选引擎指纹同时覆盖源码与扩展字节；重新编译或换包会使旧证据重新核验。

构建目录中的 binaryHash 是签名前产物校验值；安装包代码签名可能改变扩展字节，运行时引擎指纹使用实际安装文件计算。
