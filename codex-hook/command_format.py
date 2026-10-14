"""One command representation for generation, ownership and validation."""
import base64
import re


def literal(value):return "'"+str(value).replace("'","''")+"'"


def invocation(python,script,config):
    return '& '+literal(python)+' '+literal(script)+' --config '+literal(config)+' --owner codex-band-bridge'


def format_command(python,script,config):
    encoded=base64.b64encode(invocation(python,script,config).encode('utf-16-le')).decode('ascii')
    return 'powershell.exe -NoProfile -NonInteractive -EncodedCommand '+encoded


def decode_command(command):
    match=re.fullmatch(r'powershell\.exe -NoProfile -NonInteractive -EncodedCommand ([A-Za-z0-9+/=]+)',command)
    if not match:return command
    try:return base64.b64decode(match[1],validate=True).decode('utf-16-le')
    except (ValueError,UnicodeError):return ''


def parse_invocation(command):
    text=decode_command(command)
    quoted=r"'((?:[^']|'')*)'"
    match=re.fullmatch(r'& '+quoted+' '+quoted+r' --config '+quoted+r' --owner codex-band-bridge',text)
    return tuple(s.replace("''","'") for s in match.groups()) if match else None
