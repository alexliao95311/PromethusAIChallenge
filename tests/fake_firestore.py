"""A minimal in-memory fake of the google-cloud-firestore client surface.

Implements just enough of `client.collection(name).document(id).set(data) /
.get().exists / .get().to_dict()` for LessonRepository to be unit tested
without a live Firestore project or the Firestore emulator.
"""


class FakeDocumentSnapshot:
    def __init__(self, data):
        self._data = data

    @property
    def exists(self):
        return self._data is not None

    def to_dict(self):
        return self._data


class FakeDocumentRef:
    def __init__(self, collection_store, doc_id):
        self._store = collection_store
        self._doc_id = doc_id

    def set(self, data):
        self._store[self._doc_id] = dict(data)

    def get(self):
        return FakeDocumentSnapshot(self._store.get(self._doc_id))

    def delete(self):
        self._store.pop(self._doc_id, None)


class FakeCollectionRef:
    def __init__(self, collection_store):
        self._store = collection_store

    def document(self, doc_id):
        return FakeDocumentRef(self._store, doc_id)


class FakeFirestoreClient:
    def __init__(self):
        self._data = {}

    def collection(self, name):
        self._data.setdefault(name, {})
        return FakeCollectionRef(self._data[name])
