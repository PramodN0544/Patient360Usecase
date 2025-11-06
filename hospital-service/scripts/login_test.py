import urllib.parse, urllib.request, urllib.error

data = urllib.parse.urlencode({'username':'doesnotexist@example.com','password':'badpass'}).encode()
req = urllib.request.Request('http://127.0.0.1:8000/auth/token', data=data, method='POST')
try:
    with urllib.request.urlopen(req) as resp:
        body = resp.read().decode()
        print('STATUS', resp.status)
        print('BODY', body)
except urllib.error.HTTPError as e:
    print('HTTPError', e.code)
    try:
        print(e.read().decode())
    except Exception as _:
        pass
except Exception as e:
    print('ERROR', e)
