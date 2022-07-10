import asyncio
import json
import typing


class InhibitSource:

    def __init__(self, name: str = ""):
        self.name = name
        self.is_override = False  # This is a flag to indicate that whatever this source will override all other sources
        self.should_inhibit = False  # This is a flag to indicate if we should inhibit or not

        self.shutdown = False  # This is a flag to indicate to this source that it should shut down
        self.inhibit_event = asyncio.Event()  # This is an event that is called when we change the inhibit state

        # These values are set by the inhibitor not the source
        self.inhibiting = False  # This is a flag to indicate if we are currently inhibiting or not
        self.inhibited_by = []  # This is a list of sources that are inhibiting us
        self.overridden = False  # This is a flag to indicate if we are currently overridden or not
        self.overridden_by = []  # This is a list of sources that are overriding us
        self.qbt_connection = None  # Indicates if the inhibitor is connected to qbt
        self.plex_connection = None

    def update_state(self, **kwargs):
        """Update locals via kwargs"""
        for key, value in kwargs.items():
            setattr(self, key, value)


class InhibitHolder:

    def __init__(self):
        self.sources = []

    def append(self, source: InhibitSource):
        self.sources.append(source)

    def remove_by_name(self, source: str):
        for source in self.sources:
            if source.name == source:
                self.sources.remove(source)
                return
        raise ValueError("Source not found")

    def remove_by_type(self, source_type: type):
        for source in self.sources:
            if isinstance(source, source_type):
                self.sources.remove(source)

    def get_source(self, name: str):
        for source in self.sources:
            if source.name == name:
                return source
        return None

    def update_state(self, **kwargs):
        for source in self.sources:
            source.update_state(**kwargs)
            source.inhibit_event.set()

    def refresh_state(self):
        for source in self.sources:
            source.inhibit_event.set()

    def silent_update_state(self, **kwargs):
        for source in self.sources:
            source.update_state(**kwargs)

    def get_by_type(self, source_type: type):
        for source in self.sources:
            if isinstance(source, source_type):
                return source
        return None

    def dump_names(self):
        return [str(source) for source in self.sources]

    def __iter__(self):
        return self.sources.__iter__()


class PlexInhibitor(InhibitSource):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.total_sessions = 0
        self.connected_to_plex = False

    def __str__(self):
        return f"Plex({self.total_sessions})"

    def __repr__(self):
        return self.__str__()


class WebInhibitor(InhibitSource):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def __str__(self):
        return f"Web"

    def __repr__(self):
        return self.__str__()


class APIInhibitor(InhibitSource):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def __str__(self):
        return f"API"

    def __repr__(self):
        return self.__str__()


class APIMessageTX:

    def __init__(self, **kwargs):
        self.kwargs = kwargs

    def __str__(self):
        """Dump the api content to json"""
        return json.dumps(self.kwargs)

    def encode(self, encoding):
        """Encode the api content to bytes"""
        return self.__str__().encode(encoding) + b"\n\r"


class APIMessageRX:

    def __init__(self, json_raw: typing.Union[str, bytes]):
        """Load the api content from bytes"""
        if isinstance(json_raw, bytes):
            json_raw = json_raw.decode('utf-8')
        self.__dict__.update(json.loads(json_raw))  # Load the json into the locals()

    def __str__(self):
        """Dump the api content to json"""
        return json.dumps(self.__dict__)

    def encode(self, encoding):
        """Encode the api content to bytes"""
        return self.__str__().encode(encoding)
