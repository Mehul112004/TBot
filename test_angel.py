import http.client

conn = http.client.HTTPSConnection("apiconnect.angelone.in")
payload = "{\r\n     \"exchange\": \"NSE\",\r\n     \"symboltoken\": \"3045\",\r\n     \"interval\": \"ONE_MINUTE\",\r\n    \"fromdate\": \"2021-02-08 09:00\",\r\n     \"todate\": \"2021-02-08 09:16\"\r\n}"
headers = {
  'X-PrivateKey': 'KzcogBOS',
  'Accept': 'application/json',
  'X-SourceID': 'WEB',
  'X-UserType': 'USER',
  'Authorization': 'Bearer AUTHORIZATION_TOKEN',
  'Accept': 'application/json',
  'X-SourceID': 'WEB',
  'Content-Type': 'application/json'
}
conn.request("POST", "/rest/secure/angelbroking/historical/v1/getCandleData", payload, headers)
res = conn.getresponse()
data = res.read()
print(data.decode("utf-8"))
    