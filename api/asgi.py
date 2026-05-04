import json
from urllib.request import Request, urlopen

def get_block_height():
    url = "https://mainnet.ackinacki.org/graphql"

    payload = json.dumps({
        "query": """
        query GetBlocks($limit: Int!) {
          blockchain {
            blocks(last: $limit) {
              nodes {
                seq_no
              }
            }
          }
        }
        """,
        "variables": {"limit": 1}
    }).encode()

    req = Request(
        url,
        data=payload,
        headers={
            "Content-Type": "application/json",
            "User-Agent": "vercel-bot"
        },
        method="POST"
    )

    with urlopen(req, timeout=10) as res:
        data = json.loads(res.read().decode())

    return data["data"]["blockchain"]["blocks"]["nodes"][0]["seq_no"]


# 🔹 Vercel entry point
async def app(scope, receive, send):
    if scope["type"] == "http":
        try:
            height = get_block_height()

            response = {
                "status": "ok",
                "block_height": height
            }

        except Exception as e:
            response = {
                "status": "error",
                "message": str(e)
            }

        await send({
            "type": "http.response.start",
            "status": 200,
            "headers": [(b"content-type", b"application/json")]
        })

        await send({
            "type": "http.response.body",
            "body": json.dumps(response).encode()
        })
