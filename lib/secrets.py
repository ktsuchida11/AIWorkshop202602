# 環境変数からSecrets名を取得するためのモジュール
import os

def get_secret_name(env_var: str) -> str:
    """
    指定された環境変数からSecrets名を取得します。

    Args:
        env_var (str): 環境変数の名前

    Returns:
        str: 環境変数に設定されたSecrets名
    """
    secret_name = os.getenv(env_var)
    if not secret_name:
        raise ValueError(f"Environment variable '{env_var}' is not set.")
    return secret_name


# AWS Secrets Managerからシークレットを取得するための関数
def fetch_secret_from_aws(secret_name: str) -> dict:
    """
    AWS Secrets Managerからシークレットを取得します。

    Args:
        secret_name (str): 取得するシークレットの名前

    Returns:
        dict: 取得したシークレットの内容
    """
    import boto3
    from botocore.exceptions import ClientError
    import json

    client = boto3.client('secretsmanager', region_name='ap-northeast-1')

    try:
        get_secret_value_response = client.get_secret_value(SecretId=secret_name)
    except ClientError as e:
        raise e

    secret = get_secret_value_response['SecretString']
    return json.loads(secret)


# 使用例
if __name__ == "__main__":
    secret_env_var = "MY_SECRET_NAME"
    try:
        secret_name = get_secret_name(secret_env_var)
        secret_data = fetch_secret_from_aws(secret_name)
        print("Fetched secret data:", secret_data)
    except Exception as e:
        print("Error:", e)