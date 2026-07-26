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


class FakeQuery:
    """Minimal fake of a Firestore query -- supports only equality `where`
    filters, chained, followed by `.stream()`. That's the only query shape
    LessonRepository.list_debate_reflections needs."""

    def __init__(self, docs):
        self._docs = docs

    def where(self, field, op, value):
        if op != "==":
            raise NotImplementedError("FakeQuery only supports '==' filters")
        return FakeQuery([d for d in self._docs if d.get(field) == value])

    def stream(self):
        return [FakeDocumentSnapshot(d) for d in self._docs]


class FakeCollectionRef:
    def __init__(self, collection_store):
        self._store = collection_store

    def document(self, doc_id):
        return FakeDocumentRef(self._store, doc_id)

    def where(self, field, op, value):
        return FakeQuery(list(self._store.values())).where(field, op, value)


class FakeFirestoreClient:
    def __init__(self):
        self._data = {}

    def collection(self, name):
        self._data.setdefault(name, {})
        return FakeCollectionRef(self._data[name])
