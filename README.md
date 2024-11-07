# Trade Accounting

A primitive trade accounting system relying on RegEx-ing tastytrade fill confirms.

I want to automate accounting -- this is the part of trading I hate the most but equally, is almost as important as the
trade itself. If you can not account for your trades and your decisions, what are your trades worth to anyone? I
downright hate doing this manually -- it's a humongous pain. The purpose of this repo is to automate this -- albeit in a
very primitive way.

The ultimate goal is for this script to run continuously and scan every new email entering my inbox. If it's
from `tastytrade` and contains the word `Order` in the subject header -- regex it and extract the relevant information:

```json
{
  "order_id": "string of numbers, e.g. 123456789",
  "date_received": "timestamp of when tasty received my order, e.g. 2024-11-06T09:42:21",
  "order_type": "what kind of order, e.g. Limit @ 1.10 Credit",
  "legs": [
    {
      "action": "direction, e.g. Bought | Sold",
      "quantity": "integer -- how many, e.g. 1",
      "symbol": "what symbol, e.g. SPX",
      "expiration": "for which expiration, e.g. 2024-01-06T00:00:00",
      "option_type": "which option, e.g. Put",
      "strike": "float -- strike price, e.g 1234.5",
      "fill_price": "float -- what price did we get filled at, e.g. 6.45",
      "fill_time": "timestamp, what time did we get filled, e.g. 2024-11-06T09:43:54"
    }
  ]
}
```

`legs` is a list of dictionaries with entries for whatever number of legs per trade. If it's a multi-legged order, those
will always come through to us in a single fill confirm. Each leg gets its own entry in the `legs` list. That
whole `trade`
object goes in a database where we can make efficient use of it. Perhaps in an Excel file for now, but realistically
these objects will live in a MongoDB.

In the future, I need to work with the API to get my raw input. In other words, to hook up to the account streamer and
asynchronously retrieve whenever a trade sees a status change. Once we have order status `filled`, record the JSON
object we get back from the websocket in the MongoDB instead of regexing over fill confirms. Could still use this code
as a validation tool at that point, to check whether the websocket response equals the fill confirm. Because if it
doesn't, this is a problem.
