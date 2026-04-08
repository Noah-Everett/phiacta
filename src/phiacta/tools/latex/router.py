# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

"""LaTeX tool router — POST /compile triggers compilation."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from phiacta.core.models.user import User
from phiacta.core.tool_deps import get_current_user, get_job_worker
from phiacta.jobs.worker import JobWorker
from phiacta.tools.latex.schemas import CompileRequest, CompileResponse

router = APIRouter()


@router.post("/compile", response_model=CompileResponse)
async def compile_latex(
    request: CompileRequest,
    user: User = Depends(get_current_user),
    worker: JobWorker = Depends(get_job_worker),
) -> CompileResponse:
    """Compile an entry's LaTeX source to PDF.

    Reads ``.phiacta/content.tex`` (or ``content/main.tex``), compiles
    with tectonic, and stores the PDF via the compiled_content extension.
    """
    job = await worker.submit_and_wait(
        job_type="latex",
        input=request.model_dump(mode="json"),
        submitted_by=user.id,
        entry_id=request.entry_id,
        timeout_seconds=120,
    )

    if job.status == "failed":
        raise HTTPException(status_code=500, detail=job.last_error or "Compilation failed")

    result = job.result or {}
    return CompileResponse(
        success=result.get("success", False),
        log=result.get("log", ""),
        file_size=result.get("file_size"),
    )
