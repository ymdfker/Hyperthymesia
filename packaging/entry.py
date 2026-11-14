"""打包入口：PyInstaller 以此为主脚本，打出单个可执行文件 hyperthymesia。"""
import sys

from hyperthymesia.__main__ import main

if __name__ == '__main__':
    sys.exit(main())
