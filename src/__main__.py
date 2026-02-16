"""InfoHunter 入口点

支持 python -m src 运行。
"""

import asyncio
from src.main import main

if __name__ == "__main__":
    asyncio.run(main())
