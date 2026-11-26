"""业务路由汇总：所有模块共用一套资源路由，由领域服务完成分派。"""
from __future__ import annotations

from app.routers import measure_import, resource

# 导入确认路由的固定路径必须先于通用 /api/{module} 注册。
ROUTERS = [measure_import, resource]
