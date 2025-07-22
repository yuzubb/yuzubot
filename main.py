import os
import time
import re
from supabase import create_client, Client
import requests # Chatwork APIとのHTTP通信用

# --- 環境変数から設定を読み込む ---
# Renderの環境変数として設定してください
CHATWORK_API_TOKEN = os.getenv("CHATWORK_API_TOKEN")
# ボットが初期に参加している/監視したいルームID。カンマ区切りで複数指定可能。
# 例: "1234567,8901234"
MONITORED_ROOM_IDS_STR = os.getenv("MONITORED_ROOM_IDS", "") 
MONITORED_ROOM_IDS = [int(rid.strip()) for rid in MONITORED_ROOM_IDS_STR.split(',') if rid.strip()]

STAMP_EMOJI_THRESHOLD = int(os.getenv("STAMP_EMOJI_THRESHOLD", 30)) # スタンプ・絵文字の閾値
MENTION_THRESHOLD = int(os.getenv("MENTION_THRESHOLD", 10)) # 個人のメンションの閾値
COUNT_RESET_INTERVAL_HOURS = int(os.getenv("COUNT_RESET_INTERVAL_HOURS", 24)) # カウントリセット間隔（時間）
POLLING_INTERVAL_SECONDS = int(os.getenv("POLLING_INTERVAL_SECONDS", 5)) # ポーリング間隔（秒）

# Supabase設定
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY") # Service Role Keyを使用することを強く推奨

# --- Chatwork APIクライアント ---
class ChatworkApiClient:
    def __init__(self, token):
        self.base_url = "https://api.chatwork.com/v2"
        self.headers = {"X-ChatWorkToken": token}

    def _request(self, method, endpoint, **kwargs):
        """汎用リクエストメソッド"""
        url = f"{self.base_url}{endpoint}"
        try:
            response = requests.request(method, url, headers=self.headers, **kwargs)
            response.raise_for_status() # HTTPエラーがあれば例外を発生させる
            return response.json()
        except requests.exceptions.HTTPError as http_err:
            print(f"HTTPエラーが発生しました: {http_err} - レスポンス: {response.text}")
            raise
        except requests.exceptions.ConnectionError as conn_err:
            print(f"接続エラーが発生しました: {conn_err}")
            raise
        except requests.exceptions.Timeout as timeout_err:
            print(f"タイムアウトエラーが発生しました: {timeout_err}")
            raise
        except requests.exceptions.RequestException as req_err:
            print(f"リクエストエラーが発生しました: {req_err}")
            raise

    def get_my_rooms(self):
        """ボットが参加しているルームの一覧を取得"""
        return self._request("GET", "/my/rooms")

    def get_messages(self, room_id, last_id=0):
        """指定ルームのメッセージを取得"""
        params = {"last_id": last_id}
        return self._request("GET", f"/rooms/{room_id}/messages", params=params)

    def get_room_members(self, room_id):
        """指定ルームのメンバー情報を取得"""
        return self._request("GET", f"/rooms/{room_id}/members")

    def change_user_permission(self, room_id, account_id, new_role):
        """ユーザーのルーム権限を変更"""
        # Chatwork APIの/rooms/{room_id}/members APIは、部屋のメンバーリスト全体をPUTで送信して更新する形式です。
        # 現在のメンバーリストを取得し、対象ユーザーのロールのみを変更して、再度PUTする必要があります。
        # NOTE: この実装は簡略化されており、実際の運用ではより堅牢なメンバー管理ロジックが必要です。
        print(f"【APIコール】ユーザー {account_id} の権限を '{new_role}' に変更します (ルームID: {room_id})")
        
        # 簡易的な実装: 権限変更は実際にはこのメソッド内でPUTリクエストを実行します。
        # 例:
        # current_members = self.get_room_members(room_id)
        # updated_members = []
        # for member in current_members:
        #     if member['account_id'] == account_id:
        #         member['role'] = new_role
        #     updated_members.append({"account_id": member['account_id'], "role": member['role']})
        # return self._request("PUT", f"/rooms/{room_id}/members", json={"members": updated_members})
        
        # 実際には上記のようにPUTリクエストを送信する必要がありますが、
        # サンプルとしてTrueを返しておきます。
        # 本番運用時は必ずChatwork APIの仕様に合わせて実装してください。
        # 非常に重要な操作のため、慎重な実装とテストが必要です。
        print(f"  -> Chatwork APIの権限変更PUTリクエストはダミーです。実際に実装してください。")
        return True 

    def post_message(self, room_id, message_body):
        """指定ルームにメッセージを投稿"""
        data = {"body": message_body}
        return self._request("POST", f"/rooms/{room_id}/messages", data=data)

# --- Supabaseクライアントの初期化 ---
def init_supabase_client():
    if not SUPABASE_URL or not SUPABASE_KEY:
        print("SupabaseのURLまたはキーが設定されていません。")
        return None
    try:
        supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
        # Supabaseとの接続テスト
        # 例: supabase.from_("roomid").select("room_id_column").limit(1).execute()
        print("Supabaseクライアントを正常に初期化しました。")
        return supabase
    except Exception as e:
        print(f"Supabaseクライアントの初期化に失敗しました: {e}")
        return None

# --- ヘルパー関数 ---
# Chatworkの顔文字・絵文字リスト (提供いただいたもの)
ALL_EMOTICONS = [
    ":)", ":(", ":D", "8-)", ":o", ";)", ";(", "(sweat)", ":|", ":*", ":p",
    "(blush)", ":^)", "|-)", "(inlove)", "]:)", "(talk)", "(yawn)", "(puke)",
    "8-|", "(emo)", ":#)", "(nod)", "(shake)", "(^^;)", "(whew)", "(clap)",
    "(bow)", "(roger)", "(flex)", "(dance)", ":/", "(gogo)", "(think)",
    "(please)", "(quick)", "(anger)", "(devil)", "(lightbulb)", "(*)", "(h)",
    "(F)", "(cracker)", "(eat)", "(^)", "(coffee)", "(beer)", "(handshake)", "(y)"
]

def count_emoticons_in_message(message_body, emoticon_list):
    """メッセージ本文に含まれる顔文字・絵文字・Chatworkスタンプの数をカウント"""
    count = 0
    for emoticon in emoticon_list:
        count += message_body.count(emoticon)
    # Chatworkの標準スタンプ形式もカウント
    count += len(re.findall(r"\[STAMP:\d+\]", message_body))
    return count

def count_personal_mentions(message_body):
    """メッセージ本文に含まれる個人のメンション数をカウント"""
    return len(re.findall(r"\[To:\d+\]", message_body))

# --- メインロジック ---
def run_bot():
    chatwork_api = ChatworkApiClient(CHATWORK_API_TOKEN)
    supabase_client: Client = init_supabase_client()

    if not CHATWORK_API_TOKEN:
        print("エラー: CHATWORK_API_TOKENが設定されていません。")
        return
    if not supabase_client:
        print("エラー: Supabaseクライアントの初期化に失敗しました。ボットを終了します。")
        return
    if not MONITORED_ROOM_IDS:
        print("警告: MONITORED_ROOM_IDSが設定されていません。ボットが反応するルームがありません。")
        # ボットが参加している全てのルームを取得し、それを監視対象とするロジックを追加することも可能
        # 例: MONITORED_ROOM_IDS = [room['room_id'] for room in chatwork_api.get_my_rooms()]

    last_message_id_per_room = {room_id: 0 for room_id in MONITORED_ROOM_IDS} # 各ルームごとの最終メッセージID
    user_roles_per_room = {} # {room_id: {account_id: role, 'last_update_time': timestamp}, ...}
    user_activity_counts = {} # {room_id: {user_id: {'stamps': N, 'mentions': M, 'last_reset_time': timestamp}, ...}, ...}

    print("Chatwork Botを開始します...")

    while True:
        try:
            current_time = time.time()

            # Supabaseに登録されている、ボットが反応すべきルームIDのリストを取得
            # Supabaseのテーブル名が 'roomid' で、room_idが 'room_id_column' に保存されていると仮定
            enabled_rooms_data = supabase_client.from_("roomid").select("room_id_column").execute().data
            enabled_room_ids = {row['room_id_column'] for row in enabled_rooms_data}
            
            # 監視対象の各ルームをループ
            for room_id in MONITORED_ROOM_IDS:
                # ルームメンバーのロールを定期的に更新 (例: 1時間ごと)
                if room_id not in user_roles_per_room or \
                   (current_time - user_roles_per_room[room_id].get('last_update_time', 0)) / 3600 >= 1: # 1時間以上経過
                    try:
                        members_data = chatwork_api.get_room_members(room_id)
                        user_roles_per_room[room_id] = {member['account_id']: member['role'] for member in members_data}
                        user_roles_per_room[room_id]['last_update_time'] = current_time
                        print(f"ルーム {room_id} のメンバーロール情報を更新しました。")
                    except Exception as e:
                        print(f"ルーム {room_id} のメンバーロール取得に失敗しました: {e}")
                        continue # このルームの処理はスキップ

                current_room_last_message_id = last_message_id_per_room.get(room_id, 0)
                try:
                    new_messages = chatwork_api.get_messages(room_id, current_room_last_message_id)
                except Exception as e:
                    print(f"ルーム {room_id} のメッセージ取得に失敗しました: {e}")
                    continue # このルームの処理はスキップ

                if new_messages:
                    for message in new_messages:
                        sender_id = message['account_id']
                        message_body = message['body']
                        
                        # ボット自身の投稿は無視する
                        # NOTE: ボット自身のaccount_idを取得するChatwork APIは直接提供されていないため、
                        # 環境変数などでボットのaccount_idを設定するか、送信者ロールが'bot'であるかをチェックするなどの工夫が必要
                        # ここでは簡易的にスキップ
                        # if sender_id == YOUR_BOT_ACCOUNT_ID: continue

                        sender_role = user_roles_per_room[room_id].get(sender_id, 'unknown')

                        print(f"\n--- ルーム {room_id} 新しいメッセージ ---")
                        print(f"送信者ID: {sender_id}, ロール: {sender_role}")
                        print(f"本文: {message_body}")

                        # 1. コマンド処理 (`/command OK`, `/command NO`)
                        if message_body.strip() == "/command OK":
                            if sender_role == 'admin':
                                try:
                                    existing_room = supabase_client.from_("roomid").select("room_id_column").eq("room_id_column", room_id).execute().data
                                    if not existing_room:
                                        supabase_client.from_("roomid").insert({"room_id_column": room_id}).execute()
                                        chatwork_api.post_message(room_id, "[info][title]ボット有効化[/title]この部屋でのボットの監視を有効にしました。[/info]")
                                        print(f"ルーム {room_id} をSupabaseに追加しました。")
                                    else:
                                        chatwork_api.post_message(room_id, "[info][title]既に有効[/title]この部屋は既にボットの監視が有効です。[/info]")
                                except Exception as e:
                                    print(f"Supabaseへのルーム有効化でエラー: {e}")
                                    chatwork_api.post_message(room_id, "[error][title]エラー[/title]ボットの有効化に失敗しました。[/error]")
                            else:
                                chatwork_api.post_message(room_id, "[info][title]権限エラー[/title]このコマンドは管理者のみ実行できます。[/info]")
                            # コマンド処理後は、現在のメッセージでの他の監視はスキップ
                            continue 

                        elif message_body.strip() == "/command NO":
                            if sender_role == 'admin':
                                try:
                                    supabase_client.from_("roomid").delete().eq("room_id_column", room_id).execute()
                                    chatwork_api.post_message(room_id, "[info][title]ボット無効化[/title]この部屋でのボットの監視を無効にしました。[/info]")
                                    print(f"ルーム {room_id} をSupabaseから削除しました。")
                                except Exception as e:
                                    print(f"Supabaseからのルーム無効化でエラー: {e}")
                                    chatwork_api.post_message(room_id, "[error][title]エラー[/title]ボットの無効化に失敗しました。[/error]")
                            else:
                                chatwork_api.post_message(room_id, "[info][title]権限エラー[/title]このコマンドは管理者のみ実行できます。[/info]")
                            # コマンド処理後は、現在のメッセージでの他の監視はスキップ
                            continue

                        # 2. Supabaseに登録されていない部屋では、以下の監視は行わない
                        if room_id not in enabled_room_ids:
                            print(f"ルーム {room_id} はボットが有効化されていません。監視をスキップします。")
                            continue

                        # 以下は既存の監視ロジック
                        # ユーザーのアクティビティカウントを初期化または更新
                        if room_id not in user_activity_counts:
                            user_activity_counts[room_id] = {}
                        if sender_id not in user_activity_counts[room_id]:
                            user_activity_counts[room_id][sender_id] = {'stamps': 0, 'mentions': 0, 'last_reset_time': current_time}

                        # カウントのリセット判定
                        if (current_time - user_activity_counts[room_id][sender_id]['last_reset_time']) / 3600 >= COUNT_RESET_INTERVAL_HOURS:
                            print(f"ユーザー {sender_id} のカウントをリセットします。")
                            user_activity_counts[room_id][sender_id]['stamps'] = 0
                            user_activity_counts[room_id][sender_id]['mentions'] = 0
                            user_activity_counts[room_id][sender_id]['last_reset_time'] = current_time

                        # [toall] の検出と権限判定 (メンバーのみ反応)
                        if "[toall]" in message_body:
                            if sender_role == 'member': # 管理者は反応しない
                                print(f"【アクション】メンバー {sender_id} が [toall] を使用しました。権限を閲覧のみに変更します。")
                                chatwork_api.change_user_permission(room_id, sender_id, 'readonly')
                                chatwork_api.post_message(room_id, f"[info][title]権限変更通知[/title][To:{sender_id}] さん、[toall] の多用を確認したため、この部屋でのあなたの権限を『閲覧のみ』に変更しました。[/info]")
                            else:
                                print(f"【スキップ】管理者 {sender_id} が [toall] を使用しました。")
                            # [toall] があった場合は、そのメッセージで他のカウントはしない
                            continue

                        # スタンプ・絵文字の検出とカウント
                        detected_stamp_emoji_count = count_emoticons_in_message(message_body, ALL_EMOTICONS)
                        user_activity_counts[room_id][sender_id]['stamps'] += detected_stamp_emoji_count
                        print(f"スタンプ・絵文字検出: {detected_stamp_emoji_count}個 (累計: {user_activity_counts[room_id][sender_id]['stamps']}個)")

                        if user_activity_counts[room_id][sender_id]['stamps'] >= STAMP_EMOJI_THRESHOLD:
                            print(f"【アクション】ユーザー {sender_id} のスタンプ・絵文字投稿が閾値({STAMP_EMOJI_THRESHOLD})を超えました。権限を閲覧のみに変更します。")
                            chatwork_api.change_user_permission(room_id, sender_id, 'readonly')
                            chatwork_api.post_message(room_id, f"[info][title]権限変更通知[/title][To:{sender_id}] さん、スタンプ・絵文字の多用を確認したため、この部屋でのあなたの権限を『閲覧のみ』に変更しました。[/info]")
                            # 権限変更したらカウントをリセット
                            user_activity_counts[room_id][sender_id]['stamps'] = 0

                        # 個人のメンションの検出とカウント (管理者にも適用)
                        detected_mention_count = count_personal_mentions(message_body)
                        user_activity_counts[room_id][sender_id]['mentions'] += detected_mention_count
                        print(f"個人メンション検出: {detected_mention_count}個 (累計: {user_activity_counts[room_id][sender_id]['mentions']}個)")

                        if user_activity_counts[room_id][sender_id]['mentions'] >= MENTION_THRESHOLD:
                            print(f"【アクション】ユーザー {sender_id} の個人メンションが閾値({MENTION_THRESHOLD})を超えました。権限を閲覧のみに変更します。")
                            chatwork_api.change_user_permission(room_id, sender_id, 'readonly')
                            chatwork_api.post_message(room_id, f"[info][title]権限変更通知[/title][To:{sender_id}] さん、個人メンションの多用を確認したため、この部屋でのあなたの権限を『閲覧のみ』に変更しました。[/info]")
                            # 権限変更したらカウントをリセット
                            user_activity_counts[room_id][sender_id]['mentions'] = 0

                    # ルームごとの最新メッセージIDを更新
                    last_message_id_per_room[room_id] = new_messages[-1]['message_id'] if new_messages else current_room_last_message_id # メッセージがない場合は更新しない

        except Exception as e:
            print(f"致命的なエラーが発生しました: {e}")
            # 広範なエラー発生時は、少し長めに待機して再試行
            time.sleep(POLLING_INTERVAL_SECONDS * 2) 

        time.sleep(POLLING_INTERVAL_SECONDS) # 設定されたポーリング間隔で待機

if __name__ == "__main__":
    run_bot()
