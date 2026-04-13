'''
  Author: DawsonLin
  Email: lin_dongsen@126.com
  Created: 2026-04-12
  Purpose: FastAPI-compatible response utilities
'''

from typing import Any, Optional
from pydantic import BaseModel


class ApiResponse(BaseModel):
    """统一的 API 响应格式"""
    code: int = 0
    data: Optional[Any] = None
    message: Optional[str] = None


def success_response(data: Any = None, message: str = "OK") -> ApiResponse:
    """
    Create a success response.
    
    Args:
        data: Response data
        message: Success message
        
    Returns:
        ApiResponse with code=0
    """
    return ApiResponse(code=0, data=data, message=message)


def error_response(message: str, code: int = -1) -> ApiResponse:
    """
    Create an error response.
    
    Args:
        message: Error message
        code: Error code (default -1)
        
    Returns:
        ApiResponse with non-zero code
    """
    return ApiResponse(code=code, data=None, message=message)
