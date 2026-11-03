"""Production entry point: no migrations, no seeding, fixed two-worker minimum."""
import os
import uvicorn
from app.config import einstellungen
def main():
    os.umask(0o077)
    cfg=einstellungen()
    uvicorn.run("app.main:app",host="0.0.0.0",port=8000,workers=2,
        proxy_headers=True,forwarded_allow_ips=os.environ.get("FP_PROXY_IPS","127.0.0.1"),
        server_header=False,access_log=False,limit_concurrency=64,timeout_keep_alive=5)
if __name__=="__main__":main()
