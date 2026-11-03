"""One-time local credentials, no values printed."""
import os,secrets
from pathlib import Path
os.umask(0o077)
folder=Path(".private")
folder.mkdir(mode=0o700)
password=secrets.token_hex(32)
for name,value in {"db-admin":secrets.token_hex(32),"db-app":password,
    "database-url":"postgresql+psycopg://fahrrad:"+password+"@db:5432/fahrrad"}.items():
    descriptor=os.open(folder/name,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o444)
    with os.fdopen(descriptor,"w") as stream:stream.write(value)
print("Private credentials created; set FP_SECRETS_DIR to absolute .private path.")
