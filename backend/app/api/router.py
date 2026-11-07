from fastapi import APIRouter

from app.api.routes import appeals, checklists, datasets, dialogs, evaluations, system

# Single API surface, in the shapes the frontend uses (docs/API_CONTRACT.md).
api_router = APIRouter(prefix="/api")
api_router.include_router(system.router)
api_router.include_router(datasets.router)
api_router.include_router(dialogs.router)
api_router.include_router(checklists.router)
api_router.include_router(evaluations.router)
api_router.include_router(appeals.router)
