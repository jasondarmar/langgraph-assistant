"""
Security — funciones de validación, sanitización y protección.
"""
import hmac
import hashlib
import logging
import re
from typing import Optional

logger = logging.getLogger(__name__)


def verify_chatwoot_signature(request_body: bytes, signature: str, secret: str) -> bool:
    """
    Valida la firma HMAC-SHA256 del webhook de Chatwoot.

    Chatwoot envía: X-Chatwoot-Webhook-Signature header con HMAC-SHA256(body, secret)

    Args:
        request_body: Raw bytes del body del request
        signature: Valor del header X-Chatwoot-Webhook-Signature
        secret: Chatwoot webhook secret desde config

    Returns:
        True si la firma es válida, False si no
    """
    if not secret or not signature:
        logger.error("[Security] Missing signature or secret")
        return False

    try:
        # Calcular HMAC esperado
        expected_signature = hmac.new(
            secret.encode("utf-8"),
            request_body,
            hashlib.sha256,
        ).hexdigest()

        # Comparar con timing-safe comparison (prevenir timing attacks)
        is_valid = hmac.compare_digest(signature, expected_signature)

        if not is_valid:
            logger.warning(f"[Security] Invalid webhook signature")

        return is_valid

    except Exception as e:
        logger.error(f"[Security] Error verifying signature: {e}")
        return False


def sanitize_for_prompt(text: Optional[str], max_length: int = 100) -> str:
    """
    Sanitiza texto antes de inyectarlo en prompts LLM.
    Previene prompt injection attacks.

    Reglas:
    - Limitar a max_length caracteres
    - Remover/escapar caracteres peligrosos
    - No permitir patrones de control de prompts

    Args:
        text: Texto a sanitizar
        max_length: Máxima longitud permitida

    Returns:
        Texto sanitizado
    """
    if not text:
        return ""

    # 1. Limitar longitud
    text = text[:max_length].strip()

    # 2. Caracteres peligrosos para prompts
    dangerous_patterns = [
        r'"""',  # Cierre de string triple
        r"'''",  # Cierre de string triple
        r"\[\s*SYSTEM",  # [SYSTEM tags
        r"\[\s*ADMIN",  # [ADMIN tags
        r"\[\s*CODE",  # [CODE tags
        r"--.*$",  # SQL-like comments
        r"#.*$",  # Python comments
        r"eval\s*\(",
        r"exec\s*\(",
        r"__.*__",  # Dunder methods
        r"import\s+",
        r"from\s+.*import",
    ]

    for pattern in dangerous_patterns:
        text = re.sub(pattern, "", text, flags=re.IGNORECASE | re.MULTILINE)

    # 3. Remover caracteres de control
    text = "".join(char for char in text if ord(char) >= 32 or char in "\n\t")

    # 4. Remover múltiples espacios/newlines consecutivos
    text = re.sub(r"\s+", " ", text)

    return text.strip()


def sanitize_for_query(text: Optional[str], max_length: int = 100) -> str:
    """
    Sanitiza texto para usar en búsquedas/queries.
    Similar a sanitize_for_prompt pero más restrictivo.

    Args:
        text: Texto a sanitizar
        max_length: Máxima longitud

    Returns:
        Texto sanitizado
    """
    if not text:
        return ""

    text = text[:max_length].strip()

    # Solo permitir caracteres seguros para búsqueda
    # Letras, números, espacios, guiones, acentos
    text = re.sub(r"[^a-zA-Z0-9\s\-áéíóúñÁÉÍÓÚÑ]", "", text)

    # Remover múltiples espacios
    text = re.sub(r"\s+", " ", text)

    return text.strip()


def mask_sensitive_data(text: str) -> str:
    """
    Redacta PII (Personally Identifiable Information) del texto.
    Usado en logs para no exponer datos sensibles.

    Redacta:
    - Números telefónicos
    - Emails
    - Números de documento
    - Direcciones IP

    Args:
        text: Texto que puede contener PII

    Returns:
        Texto con PII redactado
    """
    # Números telefónicos: +57 312 4567890
    text = re.sub(r"\+?(\d{2,3})[\s\-]?(\d{3})[\s\-]?(\d{4})", "[PHONE]", text)

    # Emails
    text = re.sub(r"[\w\.-]+@[\w\.-]+\.\w+", "[EMAIL]", text)

    # IPs
    text = re.sub(r"\b(\d{1,3}\.){3}\d{1,3}\b", "[IP]", text)

    # Números de documento (8-10 dígitos seguidos)
    text = re.sub(r"\b\d{8,10}\b", "[DOC_ID]", text)

    # Google Calendar event IDs (formato característico)
    text = re.sub(
        r"[a-z0-9]{20,}(?:@google\.com)?",
        "[EVENT_ID]",
        text,
        flags=re.IGNORECASE,
    )

    return text


def validate_rate_limit_key(key: str) -> str:
    """
    Valida y sanitiza claves de rate limiting.
    Previene que el key pueda ser atacado.

    Args:
        key: Clave a validar (típicamente IP address)

    Returns:
        Clave validada
    """
    # IP address: permitir números y puntos
    if re.match(r"^[\d\.]+$", key):
        # Validar que sea IP válida (simplemente)
        parts = key.split(".")
        if len(parts) == 4 and all(p.isdigit() and 0 <= int(p) <= 255 for p in parts):
            return key
        return "unknown"

    # Otros formatos: alphanumeric solamente
    key = re.sub(r"[^a-zA-Z0-9\-_]", "", key)
    if len(key) > 255:
        key = key[:255]

    return key or "unknown"


def is_safe_url(url: str, allowed_hosts: list[str]) -> bool:
    """
    Valida que una URL sea segura y provenga de un host permitido.
    Previene SSRF attacks.

    Args:
        url: URL a validar
        allowed_hosts: Lista de hosts permitidos (ej: ["chatwoot.com", "storage.com"])

    Returns:
        True si URL es segura
    """
    from urllib.parse import urlparse

    if not url or len(url) > 2048:
        return False

    try:
        parsed = urlparse(url)

        # Debe ser http o https
        if parsed.scheme not in ("http", "https"):
            return False

        # Host debe estar en lista permitida
        if not any(host in parsed.netloc for host in allowed_hosts):
            logger.warning(f"[Security] URL from unauthorized host: {parsed.netloc}")
            return False

        return True

    except Exception as e:
        logger.error(f"[Security] Error validating URL: {e}")
        return False
