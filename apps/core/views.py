import mimetypes

from django.contrib.admin.views.decorators import staff_member_required
from django.core.files.storage import storages
from django.http import FileResponse, Http404


@staff_member_required
def private_media(request, path):
    """Staff-only access to private uploads (organizer verification documents) when R2 isn't used."""
    storage = storages["private"]
    if ".." in path.split("/") or not storage.exists(path):
        raise Http404
    content_type, _encoding = mimetypes.guess_type(path)
    response = FileResponse(storage.open(path, "rb"), content_type=content_type or "application/octet-stream")
    response["Cache-Control"] = "private, no-store"
    response["X-Content-Type-Options"] = "nosniff"
    return response
