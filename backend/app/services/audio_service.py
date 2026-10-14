from fastapi import UploadFile
import base64
import mimetypes

class AudioService:
    @staticmethod
    async def transcribe_audio(file: UploadFile, *, api_base: str, api_key: str) -> str:
        from openai import AsyncOpenAI
        from pathlib import Path
        from app.config import settings
        if not api_base or not api_key:
            raise ValueError('尚未配置真实语音识别服务')
        content = await file.read(7_500_000 + 1)
        if not content or len(content) > 7_500_000:
            raise ValueError('音频为空或过大；百炼 qwen3-asr-flash 单次最多识别 5 分钟，Base64 编码后不能超过 10MB')
        filename = Path(file.filename or 'audio.webm').name
        mime_type = (file.content_type or mimetypes.guess_type(filename)[0] or 'audio/webm').split(';', 1)[0]
        if not mime_type.startswith('audio/'):
            raise ValueError('上传的文件不是可识别的音频格式')
        data_url = f'data:{mime_type};base64,{base64.b64encode(content).decode("ascii")}'
        async with AsyncOpenAI(api_key=api_key, base_url=api_base, timeout=60, max_retries=1) as client:
            result = await client.chat.completions.create(
                model=settings.STT_MODEL,
                messages=[{
                    'role': 'user',
                    'content': [{
                        'type': 'input_audio',
                        'input_audio': {'data': data_url},
                    }],
                }],
                extra_body={'asr_options': {'enable_itn': True}},
            )
            transcript = result.choices[0].message.content
            if isinstance(transcript, list):
                transcript = ''.join(str(part.get('text', '')) for part in transcript if isinstance(part, dict))
            if not transcript or not transcript.strip():
                raise ValueError('没有识别到语音内容，请说话后重试')
            return transcript.strip()
