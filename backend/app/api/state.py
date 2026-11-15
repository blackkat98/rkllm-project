from typing import Annotated

from fastapi import Depends, Request

from app.engine.worker import EngineWorker
from app.services.chat import ChatService


def get_worker(request: Request) -> EngineWorker:
    return request.app.state.worker


def get_chat(request: Request) -> ChatService:
    return request.app.state.chat


WorkerDep = Annotated[EngineWorker, Depends(get_worker)]
ChatDep = Annotated[ChatService, Depends(get_chat)]
