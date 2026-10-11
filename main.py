import argparse
import uvicorn

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='텔레그램 트렌드 대시보드')
    parser.add_argument('--port', type=int, default=8010)
    args = parser.parse_args()
    uvicorn.run('app.main:app', host='127.0.0.1', port=args.port)
