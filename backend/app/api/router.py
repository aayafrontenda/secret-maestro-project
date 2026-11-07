from fastapi import APIRouter

from app.api.routes import appeals, checklists, dialogs, evaluations, system

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(system.router)
api_router.include_router(dialogs.router)
api_router.include_router(checklists.router)
api_router.include_router(evaluations.router)
api_router.include_router(appeals.router)
