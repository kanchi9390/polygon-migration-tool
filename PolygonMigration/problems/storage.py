"""
Storage abstraction for test-case files.

The migration flow only talks to ``BaseStorage``. Each cloud provider is one
subclass that implements three operations. The provider is chosen with the
``STORAGE_PROVIDER`` environment variable (see ``get_storage``).

File layout (same for every provider, inside the bucket/container):

    test_cases/{problem_id}/{test_number:02d}      # input file
    test_cases/{problem_id}/{test_number:02d}.a    # output file
    test_cases/{problem_id}/custom_checker[.exe|.cpp]
"""
import logging
from abc import ABC, abstractmethod

from django.conf import settings

logger = logging.getLogger(__name__)


class StorageConfigError(Exception):
    """Raised when the selected storage provider is missing configuration."""


class BaseStorage(ABC):
    """Interface the migration flow depends on. Providers implement the abstract methods."""

    @staticmethod
    def test_case_key(problem_id, test_number, is_output=False):
        """Object name for one test-case file; shared by all providers so the layout stays identical."""
        key = f"test_cases/{problem_id}/{test_number:02d}"
        return f"{key}.a" if is_output else key

    @staticmethod
    def problem_prefix(problem_id):
        return f"test_cases/{problem_id}/"

    @abstractmethod
    def upload_bytes(self, key, data):
        """Create or overwrite the object ``key`` with ``data`` (bytes)."""

    @abstractmethod
    def delete_prefix(self, prefix):
        """Delete every object whose name starts with ``prefix``."""

    @abstractmethod
    def list_keys(self, prefix):
        """Return the object names that start with ``prefix`` (used to verify uploads)."""

    # --- shared behaviour built on the primitives above -------------------

    def upload_test_case(self, problem_id, test_number, input_data, output_data):
        """Upload the input and output files of one test case."""
        self.upload_bytes(self.test_case_key(problem_id, test_number), input_data.encode("utf-8"))
        self.upload_bytes(self.test_case_key(problem_id, test_number, is_output=True), output_data.encode("utf-8"))
        logger.info("Uploaded test #%s for problem %s", test_number, problem_id)

    def empty_problem(self, problem_id):
        """Remove all previously uploaded files for a problem (so a re-migration starts clean)."""
        self.delete_prefix(self.problem_prefix(problem_id))

    def upload_problem_file(self, problem_id, filename, data):
        """Upload an extra per-problem file such as the custom checker."""
        self.upload_bytes(f"{self.problem_prefix(problem_id)}{filename}", data)


class AzureStorage(BaseStorage):
    """Azure Blob Storage. Wraps the existing AzureBlobManager (username/password auth)."""

    def __init__(self, account_url, tenant_id, client_id, username, password, container_name):
        from problems.AzureTestcase import AzureBlobManager

        self.container_name = container_name
        self._manager = AzureBlobManager(
            account_url=account_url,
            tenant_id=tenant_id,
            client_id=client_id,
            username=username,
            password=password,
        )
        self._container = self._manager.blob_service_client.get_container_client(container_name)

    def upload_bytes(self, key, data):
        self._container.get_blob_client(key).upload_blob(data, overwrite=True)

    def delete_prefix(self, prefix):
        for key in self.list_keys(prefix):
            self._container.delete_blob(key)

    def list_keys(self, prefix):
        return [blob.name for blob in self._container.list_blobs(name_starts_with=prefix)]


class S3CompatibleStorage(BaseStorage):
    """
    Any S3-compatible store: RustFS, MinIO, AWS S3, Cloudflare R2, Backblaze B2...
    Only the endpoint and keys change between them.
    """

    def __init__(self, endpoint, access_key, secret_key, bucket_name, secure=False, region="us-east-1"):
        import boto3
        from botocore.config import Config

        scheme = "https" if secure else "http"
        endpoint_url = endpoint if "://" in endpoint else f"{scheme}://{endpoint}"
        self.bucket_name = bucket_name
        self._client = boto3.client(
            "s3",
            endpoint_url=endpoint_url,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            region_name=region,
            config=Config(s3={"addressing_style": "path"}),
        )

    def upload_bytes(self, key, data):
        self._client.put_object(Bucket=self.bucket_name, Key=key, Body=data)

    def list_keys(self, prefix):
        keys = []
        paginator = self._client.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=self.bucket_name, Prefix=prefix):
            keys.extend(obj["Key"] for obj in page.get("Contents", []))
        return keys

    def delete_prefix(self, prefix):
        keys = self.list_keys(prefix)
        # delete_objects accepts at most 1000 keys per request
        for start in range(0, len(keys), 1000):
            batch = [{"Key": k} for k in keys[start:start + 1000]]
            self._client.delete_objects(Bucket=self.bucket_name, Delete={"Objects": batch})
        logger.info("Deleted %d objects under %s", len(keys), prefix)


def _require(names):
    """Return the settings values for ``names`` or raise a clear error listing the missing ones."""
    values = {name: getattr(settings, name, None) for name in names}
    missing = [name for name, value in values.items() if not value]
    if missing:
        raise StorageConfigError(f"Missing storage settings in .env: {', '.join(missing)}")
    return values


def get_storage():
    """Build the storage provider selected by STORAGE_PROVIDER (default: azure)."""
    provider = (getattr(settings, "STORAGE_PROVIDER", None) or "azure").strip().lower()

    if provider == "azure":
        v = _require([
            "AZURE_STORAGE_ACCOUNT_URL", "AZURE_TENANT_ID", "AZURE_CLIENT_ID",
            "AZURE_USERNAME", "AZURE_PASSWORD", "AZURE_CONTAINER_NAME",
        ])
        return AzureStorage(
            v["AZURE_STORAGE_ACCOUNT_URL"], v["AZURE_TENANT_ID"], v["AZURE_CLIENT_ID"],
            v["AZURE_USERNAME"], v["AZURE_PASSWORD"], v["AZURE_CONTAINER_NAME"],
        )

    if provider in ("minio", "s3", "rustfs", "r2"):
        v = _require(["MINIO_ENDPOINT", "MINIO_ACCESS_KEY", "MINIO_SECRET_KEY", "MINIO_BUCKET_NAME"])
        return S3CompatibleStorage(
            endpoint=v["MINIO_ENDPOINT"],
            access_key=v["MINIO_ACCESS_KEY"],
            secret_key=v["MINIO_SECRET_KEY"],
            bucket_name=v["MINIO_BUCKET_NAME"],
            secure=settings.MINIO_SECURE,
        )

    raise StorageConfigError(f"Unknown STORAGE_PROVIDER '{provider}'. Use 'azure' or 'minio'.")
