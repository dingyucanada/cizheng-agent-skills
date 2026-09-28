import os
import uvicorn

if __name__ == '__main__':
    uvicorn.run('cizheng.api:create_app', factory=True, host='127.0.0.1', port=int(os.getenv('CIZHENG_PORT','8778')), workers=1)
