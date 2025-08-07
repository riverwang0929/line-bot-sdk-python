# -*- coding: utf-8 -*-

#  Licensed under the Apache License, Version 2.0 (the "License"); you may
#  not use this file except in compliance with the License. You may obtain
#  a copy of the License at
#
#       https://www.apache.org/licenses/LICENSE-2.0
#
#  Unless required by applicable law or agreed to in writing, software
#  distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#  WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#  License for the specific language governing permissions and limitations
#  under the License.

import os
import sys
import requests
from argparse import ArgumentParser

from flask import Flask, request, abort
from linebot.v3 import (
    WebhookHandler
)
from linebot.v3.exceptions import (
    InvalidSignatureError
)
from linebot.v3.messaging import (
    Configuration,
    ApiClient,
    MessagingApi,
    ReplyMessageRequest,
    TextMessage
)
from linebot.v3.webhooks import (
    MessageEvent,
    TextMessageContent,
    ImageMessageContent
)

app = Flask(__name__)

# get channel_secret and channel_access_token from your environment variable
channel_secret = os.getenv('LINE_CHANNEL_SECRET', None)
channel_access_token = os.getenv('LINE_CHANNEL_ACCESS_TOKEN', None)
dify_api_key = os.getenv('DIFY_API_KEY', None)
dify_api_url = os.getenv('DIFY_API_URL', None)


if channel_secret is None:
    print('Specify LINE_CHANNEL_SECRET as environment variable.')
    sys.exit(1)
if channel_access_token is None:
    print('Specify LINE_CHANNEL_ACCESS_TOKEN as environment variable.')
    sys.exit(1)
if dify_api_key is None:
    print('Specify DIFY_API_KEY as environment variable.')
    sys.exit(1)
if dify_api_url is None:
    print('Specify DIFY_API_URL as environment variable.')
    sys.exit(1)

handler = WebhookHandler(channel_secret)

configuration = Configuration(
    access_token=channel_access_token
)

@app.route("/callback", methods=['POST'])
def callback():
    # get X-Line-Signature header value
    signature = request.headers['X-Line-Signature']

    # get request body as text
    body = request.get_data(as_text=True)
    app.logger.info("Request body: " + body)

    # handle webhook body
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)

    return 'OK'


@handler.add(MessageEvent, message=TextMessageContent)
def handle_text_message(event):
    with ApiClient(configuration) as api_client:
        line_bot_api = MessagingApi(api_client)
        line_bot_api.reply_message_with_http_info(
            ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=[TextMessage(text='您好！請直接上傳管件圖面，我將為您進行分析。')]
            )
        )

@handler.add(MessageEvent, message=ImageMessageContent)
def handle_image_message(event):
    with ApiClient(configuration) as api_client:
        line_bot_api = MessagingApi(api_client)

        # 1. 先回覆使用者，告知已收到圖片，正在處理中
        line_bot_api.reply_message(
            ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=[TextMessage(text='已收到您的圖面，專家系統正在進行分析，請稍候約 15-30 秒...')]
            )
        )

        # 2. 從 LINE 下載使用者上傳的圖片
        message_content = line_bot_api.get_message_content(message_id=event.message.id)
        image_bytes = message_content

        # 3. 呼叫 Dify API 進行分析
        user_id = event.source.user_id
        dify_response_text = call_dify_api(user_id, image_bytes)

        # 4. 將 Dify 的分析結果以「Push Message」發送回給使用者
        from linebot.v3.messaging.api.messaging_api import PushMessageRequest
        line_bot_api.push_message(
             PushMessageRequest(
                to=user_id,
                messages=[TextMessage(text=dify_response_text)]
            )
        )


def call_dify_api(user_id, image_bytes):
    url = dify_api_url
    headers = {
        'Authorization': f'Bearer {dify_api_key}',
    }
    files = {
        'pipe_drawing_image': ('image.jpg', image_bytes, 'image/jpeg')
    }
    data = {
        'inputs': '{}',  # 可以留空
        'response_mode': 'streaming', # 或者 'blocking'
        'user': user_id,
        'conversation_id': '' # 讓 Dify 自動管理
    }

    try:
        response = requests.post(url, headers=headers, files=files, data=data, stream=True)
        response.raise_for_status()

        # 處理 streaming response
        full_response = ""
        for line in response.iter_lines():
            if line:
                decoded_line = line.decode('utf-8')
                # 簡單地拼接 data: 後的 JSON 字符串中的 content
                if decoded_line.startswith('data:'):
                    import json
                    try:
                        json_data = json.loads(decoded_line[len('data:'):])
                        if 'answer' in json_data:
                            full_response += json_data['answer']
                    except json.JSONDecodeError:
                        continue # 忽略無法解析的行
        
        return full_response if full_response else "分析完成，但未收到有效回覆。"

    except requests.exceptions.RequestException as e:
        app.logger.error(f"Dify API Error: {e}")
        return f"無法連接 Dify 專家系統，請稍後再試。錯誤：{e}"


if __name__ == "__main__":
    arg_parser = ArgumentParser(
        usage='Usage: python ' + __file__ + ' [--port <port>] [--help]'
    )
    arg_parser.add_argument('-p', '--port', type=int, default=8000, help='port')
    arg_parser.add_argument('-d', '--debug', default=False, help='debug')
    options = arg_parser.parse_args()

    app.run(debug=options.debug, port=options.port)
