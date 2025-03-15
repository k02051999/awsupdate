import boto3
import requests
from bs4 import BeautifulSoup
import datetime
import json
import os
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import smtplib

# RSS/Web情報取得用の設定
AWS_WHAT_NEW_URL = "https://aws.amazon.com/about-aws/whats-new/recent/"
AWS_BLOG_URL = "https://aws.amazon.com/blogs/aws/"

# S3バケット名（前回の更新情報を保存）
BUCKET_NAME = "your-aws-updates-bucket"
LAST_UPDATE_KEY = "last_update.json"

# メール設定
SENDER_EMAIL = "your-sender-email@example.com"
RECEIVER_EMAIL = "your-email@example.com"
SMTP_SERVER = "smtp.example.com"
SMTP_PORT = 587
SMTP_USERNAME = "your_smtp_username"
SMTP_PASSWORD = "your_smtp_password"

# Amazon Bedrock設定
bedrock_runtime = boto3.client(
    service_name='bedrock-runtime',
    region_name='us-east-1'  # 適切なリージョンに変更してください
)

def get_aws_updates():
    """AWSの最新情報を取得する"""
    updates = []
    
    # What's Newページから情報取得
    try:
        response = requests.get(AWS_WHAT_NEW_URL)
        soup = BeautifulSoup(response.content, 'html.parser')
        
        # 最新情報を抽出（サイト構造によって調整が必要）
        update_items = soup.select('.awsm-card-container')
        for item in update_items[:10]:  # 最新10件
            title_element = item.select_one('.title-wrapper h3')
            date_element = item.select_one('.date')
            link_element = item.select_one('a')
            
            if title_element and date_element and link_element:
                title = title_element.text.strip()
                date = date_element.text.strip()
                link = link_element.get('href')
                if not link.startswith('http'):
                    link = f"https://aws.amazon.com{link}"
                
                updates.append({
                    'title': title,
                    'date': date,
                    'link': link,
                    'source': 'What\'s New'
                })
    except Exception as e:
        print(f"What's New情報取得中にエラー: {str(e)}")
    
    # AWSブログから情報取得
    try:
        response = requests.get(AWS_BLOG_URL)
        soup = BeautifulSoup(response.content, 'html.parser')
        
        # ブログ記事を抽出（サイト構造によって調整が必要）
        blog_items = soup.select('.blog-post')
        for item in blog_items[:5]:  # 最新5件
            title_element = item.select_one('.blog-post-title')
            date_element = item.select_one('.blog-post-meta')
            link_element = title_element.select_one('a') if title_element else None
            
            if title_element and date_element and link_element:
                title = title_element.text.strip()
                date = date_element.text.strip().split('|')[0].strip()
                link = link_element.get('href')
                
                updates.append({
                    'title': title,
                    'date': date,
                    'link': link,
                    'source': 'AWS Blog'
                })
    except Exception as e:
        print(f"AWSブログ情報取得中にエラー: {str(e)}")
    
    return updates

def get_last_update_info():
    """S3から前回の更新情報を取得"""
    s3_client = boto3.client('s3')
    try:
        response = s3_client.get_object(Bucket=BUCKET_NAME, Key=LAST_UPDATE_KEY)
        content = response['Body'].read().decode('utf-8')
        return json.loads(content)
    except Exception as e:
        print(f"前回の更新情報取得中にエラー（初回実行の場合は問題ありません）: {str(e)}")
        return {'updates': []}

def save_current_update_info(updates):
    """現在の更新情報をS3に保存"""
    s3_client = boto3.client('s3')
    try:
        s3_client.put_object(
            Bucket=BUCKET_NAME,
            Key=LAST_UPDATE_KEY,
            Body=json.dumps({'updates': updates})
        )
    except Exception as e:
        print(f"更新情報保存中にエラー: {str(e)}")

def filter_new_updates(current_updates, last_updates):
    """新しい更新情報のみを抽出"""
    last_update_titles = [update['title'] for update in last_updates]
    return [update for update in current_updates if update['title'] not in last_update_titles]

def summarize_with_bedrock(updates):
    """Amazon Bedrockを使用して更新情報を要約"""
    if not updates:
        return "新しい更新情報はありません。"
    
    # 入力プロンプトの作成
    updates_text = "\n".join([f"- {update['title']} ({update['source']})" for update in updates])
    prompt = f"""以下のAWSサービスの更新情報を日本語で簡潔に要約し、重要なポイントをまとめてください。
技術的な観点から特に注目すべき点や活用方法についても触れてください。

{updates_text}
"""

    # Anthropic Claude 3 Sonnetモデルを使用
    try:
        response = bedrock_runtime.invoke_model(
            modelId='anthropic.claude-3-sonnet-20240229-v1:0',
            body=json.dumps({
                "anthropic_version": "bedrock-2023-05-31",
                "max_tokens": 1000,
                "messages": [
                    {
                        "role": "user",
                        "content": prompt
                    }
                ]
            })
        )
        response_body = json.loads(response.get('body').read())
        summary = response_body['content'][0]['text']
        return summary
    except Exception as e:
        print(f"Bedrock APIエラー: {str(e)}")
        # エラー時はシンプルなリスト形式で返す
        return "\n".join([f"- {update['title']} ({update['date']})\n  {update['link']}" for update in updates])

def send_email(subject, body):
    """メール送信関数"""
    msg = MIMEMultipart()
    msg['From'] = SENDER_EMAIL
    msg['To'] = RECEIVER_EMAIL
    msg['Subject'] = subject
    
    msg.attach(MIMEText(body, 'plain', 'utf-8'))
    
    try:
        server = smtplib.SMTP(SMTP_SERVER, SMTP_PORT)
        server.starttls()
        server.login(SMTP_USERNAME, SMTP_PASSWORD)
        server.send_message(msg)
        server.quit()
        print("メール送信完了")
    except Exception as e:
        print(f"メール送信エラー: {str(e)}")

def lambda_handler(event, context):
    """AWS Lambda用ハンドラー関数"""
    # 最新の更新情報を取得
    current_updates = get_aws_updates()
    
    # 前回の更新情報を取得
    last_update_info = get_last_update_info()
    last_updates = last_update_info.get('updates', [])
    
    # 新しい更新情報をフィルタリング
    new_updates = filter_new_updates(current_updates, last_updates)
    
    if new_updates:
        # Bedrockで要約
        summary = summarize_with_bedrock(new_updates)
        
        # 詳細情報の追加
        detail_section = "\n\n詳細情報:\n" + "\n".join([
            f"- {update['title']}\n  日付: {update['date']}\n  ソース: {update['source']}\n  リンク: {update['link']}"
            for update in new_updates
        ])
        
        # メール本文の作成
        email_body = f"""AWSの最新更新情報 ({datetime.datetime.now().strftime('%Y-%m-%d')})

{summary}

{detail_section}

----
このメールはAWS更新情報自動通知システムにより送信されています。
"""
        
        # メール送信
        send_email("【AWS】最新サービス更新情報", email_body)
        
        # 現在の更新情報を保存
        save_current_update_info(current_updates)
        
        return {
            'statusCode': 200,
            'body': json.dumps(f'{len(new_updates)}件の新しい更新情報を送信しました')
        }
    else:
        print("新しい更新情報はありません")
        return {
            'statusCode': 200,
            'body': json.dumps('新しい更新情報はありません')
        }

# ローカルテスト用
if __name__ == "__main__":
    lambda_handler(None, None)
