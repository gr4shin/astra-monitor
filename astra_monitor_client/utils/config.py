
import os
import sys
import json
import base64
import logging

OBFUSCATION_KEY = "AstraMonitorKey2024!@#"



def deobfuscate_config(obfuscated_str: str, key: str) -> dict:
    """Деобфусцирует строку конфигурации в словарь."""
    try:
        xored_bytes = base64.b64decode(obfuscated_str.encode('ascii'))
        b64_bytes = bytearray()
        for i, byte in enumerate(xored_bytes):
            b64_bytes.append(byte ^ ord(key[i % len(key)]))
        json_str_bytes = base64.b64decode(bytes(b64_bytes))
        data = json.loads(json_str_bytes.decode('utf-8'))
        return data
    except Exception as e:
        logging.error("❌ Ошибка деобфускации конфигурации: %s", e)
        return {}
