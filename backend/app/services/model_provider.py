"""Discover models through an OpenAI-compatible provider's authenticated /models API."""
import asyncio
from urllib.parse import urlsplit
from openai import AsyncOpenAI, APIConnectionError, APIStatusError, APITimeoutError


async def list_provider_models(base_url: str, api_key: str) -> list[str]:
    base_url = base_url.strip().rstrip('/')
    url = urlsplit(base_url)
    if url.scheme not in {'http', 'https'} or not url.hostname or url.username or url.password or url.query or url.fragment:
        raise ValueError('请输入有效的 HTTP(S) Base URL，不要包含账号、查询参数或片段')
    if not api_key.strip():
        raise ValueError('请填写供应商 API Key')
    try:
        async with asyncio.timeout(20):
            async with AsyncOpenAI(base_url=base_url, api_key=api_key, timeout=15, max_retries=0) as client:
                page = await client.models.list()
                if not isinstance(page.data, list):
                    raise ValueError('供应商返回的模型列表格式无效，请手动填写模型 ID')
                # SDK iteration follows pagination where supported.
                ids = {model.id async for model in page if isinstance(model.id, str) and model.id.strip()}
                return sorted(ids)
    except (TimeoutError, APITimeoutError):
        raise ValueError('连接超时，请检查 Base URL 和网络')
    except (TypeError, AttributeError):
        raise ValueError('供应商返回的模型列表格式无效，请手动填写模型 ID')
    except APIConnectionError:
        raise ValueError('无法连接供应商，请检查 Base URL、网络和证书')
    except APIStatusError as exc:
        if exc.status_code in {401, 403}:
            raise ValueError('供应商认证失败，请检查 API Key 和访问权限')
        if exc.status_code == 404:
            raise ValueError('供应商未提供模型列表接口，请检查 Base URL，或手动填写模型 ID')
        if exc.status_code == 429:
            raise ValueError('供应商请求限流或配额不足，请稍后重试')
        raise ValueError(f'供应商接口请求失败（HTTP {exc.status_code}）')
