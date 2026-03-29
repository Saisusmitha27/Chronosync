import os
from uuid import uuid4
from supabase import create_client
from config import SUPABASE_URL, SUPABASE_KEY, SUPABASE_STORAGE_BUCKET

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)


def insert_run(record: dict):
    return supabase.table('runs').insert(record).execute()


def update_run(run_id, record: dict):
    return supabase.table('runs').update(record).eq('id', run_id).execute()


def get_runs(limit=20):
    return supabase.table('runs').select('*').order('created_at', desc=True).limit(limit).execute()


def get_engagement(run_id):
    return supabase.table('engagement').select('*').eq('run_id', run_id).execute()


def delete_runs_by_ids(run_ids: list):
    if not run_ids:
        return None
    return supabase.table('runs').delete().in_('id', run_ids).execute()


def upload_video(file_path: str, bucket: str = None, object_name: str = None):
    if not file_path or not os.path.exists(file_path):
        raise FileNotFoundError(f'Video file not found: {file_path}')

    target_bucket = (bucket or SUPABASE_STORAGE_BUCKET or 'videos').strip()
    ext = os.path.splitext(file_path)[1] or '.mp4'
    target_name = object_name or f'linkedin/{uuid4().hex}{ext}'

    with open(file_path, 'rb') as file_obj:
        supabase.storage.from_(target_bucket).upload(
            path=target_name,
            file=file_obj,
            file_options={'content-type': 'video/mp4', 'upsert': True},
        )

    public_url = supabase.storage.from_(target_bucket).get_public_url(target_name)
    if isinstance(public_url, dict):
        return public_url.get('publicUrl') or public_url.get('publicURL') or ''
    return str(public_url or '')
