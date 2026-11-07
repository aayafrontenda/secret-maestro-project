from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.db import get_session
from app.ml.base import MLClient
from app.services.queue import EvaluationQueue

SessionDep = Annotated[AsyncSession, Depends(get_session)]
SettingsDep = Annotated[Settings, Depends(get_settings)]


def get_queue(request: Request) -> EvaluationQueue:
    return request.app.state.queue


def get_ml(request: Request) -> MLClient:
    return request.app.state.ml


QueueDep = Annotated[EvaluationQueue, Depends(get_queue)]
MLDep = Annotated[MLClient, Depends(get_ml)]
