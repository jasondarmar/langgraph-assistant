"""
SSRF Protection — previene Server-Side Request Forgery attacks.
"""
import logging
from urllib.parse import urlparse
from typing import Optional

logger = logging.getLogger(__name__)


class SSRFProtection:
    """Protección contra SSRF attacks."""

    # Hosts permitidos para descargas
    ALLOWED_AUDIO_HOSTS = {
        "chatwoot.techideaslab.com",
        "n8n.techideaslab.com",
        "localhost",
        "127.0.0.1",
    }

    # Máximo tamaño de archivo (25MB)
    MAX_FILE_SIZE = 25 * 1024 * 1024

    # Content types permitidos
    ALLOWED_CONTENT_TYPES = {
        "audio/mpeg",
        "audio/wav",
        "audio/ogg",
        "audio/opus",
        "audio/webm",
        "audio/mp3",
        "audio/mp4",
        "audio/aac",
        "application/octet-stream",
    }

    @staticmethod
    def validate_audio_url(
        url: str, allowed_hosts: Optional[set] = None
    ) -> tuple[bool, str]:
        """
        Valida que una URL de audio sea segura.

        Args:
            url: URL a validar
            allowed_hosts: Set de hosts permitidos (usa default si None)

        Returns:
            (is_valid, error_message)
        """
        if not url:
            return False, "URL vacía"

        if len(url) > 2048:
            return False, "URL demasiado larga"

        # Validar esquema
        if not url.startswith(("http://", "https://")):
            return False, "URL debe ser http o https"

        # Parse URL
        try:
            parsed = urlparse(url)
        except Exception as e:
            return False, f"URL inválida: {str(e)}"

        # Validar host
        if not allowed_hosts:
            allowed_hosts = SSRFProtection.ALLOWED_AUDIO_HOSTS

        # Remover puerto del hostname para comparación
        hostname = parsed.hostname or parsed.netloc.split(":")[0]

        if not hostname:
            return False, "Hostname no encontrado"

        # Validar contra whitelist
        if hostname not in allowed_hosts:
            logger.warning(
                f"[SSRF] URL from unauthorized host: {hostname} "
                f"(allowed: {allowed_hosts})"
            )
            return False, f"Host no autorizado: {hostname}"

        # HTTPS preferido
        if url.startswith("http://"):
            logger.warning(
                f"[SSRF] ⚠️  Audio URL using HTTP (prefer HTTPS): {url}"
            )

        return True, ""

    @staticmethod
    def validate_content_type(
        content_type: str, allowed_types: Optional[set] = None
    ) -> tuple[bool, str]:
        """
        Valida que el content-type sea permitido.

        Args:
            content_type: Content-Type del response
            allowed_types: Set de tipos permitidos

        Returns:
            (is_valid, error_message)
        """
        if not content_type:
            return False, "Content-Type vacío"

        if not allowed_types:
            allowed_types = SSRFProtection.ALLOWED_CONTENT_TYPES

        # Remover charset
        base_type = content_type.split(";")[0].strip().lower()

        if base_type not in allowed_types:
            logger.warning(
                f"[SSRF] Invalid content-type: {base_type} "
                f"(allowed: {allowed_types})"
            )
            return False, f"Content-Type no permitido: {base_type}"

        return True, ""

    @staticmethod
    def validate_file_size(
        content_length: Optional[str],
        max_size: int = MAX_FILE_SIZE,
    ) -> tuple[bool, str]:
        """
        Valida que el tamaño del archivo sea permitido.

        Args:
            content_length: Header Content-Length
            max_size: Máximo tamaño permitido en bytes

        Returns:
            (is_valid, error_message)
        """
        if not content_length:
            return True, ""  # No limite si no hay header

        try:
            size = int(content_length)
        except ValueError:
            return False, "Content-Length inválido"

        if size > max_size:
            logger.warning(
                f"[SSRF] File too large: {size} bytes (max: {max_size})"
            )
            return False, f"Archivo demasiado grande: {size} > {max_size}"

        return True, ""

    @staticmethod
    def validate_redirect(location: Optional[str]) -> tuple[bool, str]:
        """
        Valida que un redirect sea a un host permitido.

        Args:
            location: URL del redirect (Location header)

        Returns:
            (is_valid, error_message)
        """
        if not location:
            return True, ""

        # Rechazar redirects a otros hosts
        is_valid, error = SSRFProtection.validate_audio_url(location)
        if not is_valid:
            logger.warning(f"[SSRF] Redirect rejected: {error}")
        return is_valid, error
