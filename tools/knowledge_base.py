"""
Knowledge Base — base de conocimiento de la clínica dental Luna González.
Responde consultas sobre servicios, doctores, sedes y preguntas frecuentes.
"""
from typing import Optional

KNOWLEDGE_BASE = {
    "sedes": {
        "Bogotá": {
            "direccion": "Por confirmar con el cliente",
            "horario": "Lunes a viernes 8:00 AM – 6:00 PM | Sábados 8:00 AM – 1:00 PM",
        },
        "La Vega": {
            "direccion": "Por confirmar con el cliente",
            "horario": "Lunes a viernes 8:00 AM – 6:00 PM | Sábados 8:00 AM – 1:00 PM",
        },
        "Villeta": {
            "direccion": "Por confirmar con el cliente",
            "horario": "Lunes a viernes 8:00 AM – 6:00 PM | Sábados 8:00 AM – 1:00 PM",
        },
    },
    "doctores": [
        "Dr. Enrique Luna",
        "Dr. Sebastián Luna",
        "Dra. Mónica González",
    ],
    "servicios": [
        "Odontología general",
        "Ortodoncia",
        "Blanqueamiento dental",
        "Endodoncia",
        "Prótesis dental",
        "Radiografía dental",
    ],
    "faq": {
        "precio": "Los precios varían según el tratamiento y doctor. Te recomendamos agendar una valoración inicial.",
        "duracion": "La duración depende del procedimiento. Una consulta general dura entre 30 y 60 minutos.",
        "seguro": "Por favor consulta directamente en la sede si trabajan con tu aseguradora.",
        "estacionamiento": "Disponibilidad varía por sede. Consulta al llegar.",
        "formas_de_pago": "Efectivo, tarjeta débito y crédito. Consulta cuotas disponibles en sede.",
    },
}


def get_services() -> list[str]:
    return KNOWLEDGE_BASE["servicios"]


def get_doctors() -> list[str]:
    return KNOWLEDGE_BASE["doctores"]


def get_sedes() -> dict:
    return KNOWLEDGE_BASE["sedes"]


def get_sede_info(sede: str) -> Optional[dict]:
    return KNOWLEDGE_BASE["sedes"].get(sede)


def is_valid_service(service: str) -> bool:
    return any(
        service.lower() in s.lower() or s.lower() in service.lower()
        for s in KNOWLEDGE_BASE["servicios"]
    )


def is_valid_doctor(doctor: str) -> bool:
    return any(
        doctor.lower() in d.lower() or d.lower() in doctor.lower()
        for d in KNOWLEDGE_BASE["doctores"]
    )


def is_valid_sede(sede: str) -> bool:
    return sede in KNOWLEDGE_BASE["sedes"]
