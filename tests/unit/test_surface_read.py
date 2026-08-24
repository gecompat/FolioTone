from foliotone.surface.read import CursorCodec, CursorError


def test_cursor_is_opaque_and_bound_to_resource_and_sort() -> None:
    codec = CursorCodec(b"c" * 32)
    cursor = codec.encode(resource="review-queue/v1", sort="created-at-id", last_id="item-1")

    decoded = codec.decode(cursor, resource="review-queue/v1", sort="created-at-id")
    assert decoded.last_id == "item-1"

    for resource, sort in (("job-list/v1", "created-at-id"), ("review-queue/v1", "id")):
        try:
            codec.decode(cursor, resource=resource, sort=sort)
        except CursorError:
            pass
        else:  # pragma: no cover - explicit failure path for the security invariant
            raise AssertionError("cursor binding was not enforced")


def test_cursor_rejects_tampering() -> None:
    codec = CursorCodec(b"c" * 32)
    cursor = codec.encode(resource="review-queue/v1", sort="created-at-id", last_id="item-1")

    try:
        codec.decode(cursor[:-1] + "A", resource="review-queue/v1", sort="created-at-id")
    except CursorError:
        pass
    else:  # pragma: no cover - explicit failure path for the security invariant
        raise AssertionError("tampered cursor was accepted")
