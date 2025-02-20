import functools
import os
import pathlib

import pandas
import pyarrow
import pyarrow.csv
import pyarrow.feather as feather
import pyarrow.parquet as parquet
import requests

from enum import Enum


this_dir = os.path.dirname(os.path.abspath(__file__))
local_data_dir = os.path.join(this_dir, "data")
data_dir = os.getenv("BENCHMARKS_DATA_DIR", local_data_dir)
temp_dir = os.path.join(data_dir, "temp")


def _local(name):
    """Sources for unit testing, committed to benchmarks/data."""
    return os.path.join(local_data_dir, name)


def _source(name):
    """Sources downloaded from S3 and otherwise untouched."""
    return os.path.join(data_dir, name)


def _temp(name):
    """Sources generated from the canonical sources."""
    return os.path.join(temp_dir, name)


def munge_compression(c, file_type):
    if file_type == "parquet":
        c = "NONE" if c == "uncompressed" else c
    return c.lower() if file_type == "feather" else c.upper()


class SourceFormat(Enum):
    CSV = "csv"
    PARQUET = "parquet"
    FEATHER = "feather"


STORE = {
    "fanniemae_sample": {
        "path": _local("fanniemae_sample.csv"),
        "sep": "|",
        "header": None,
        "format": SourceFormat.CSV,
    },
    "nyctaxi_sample": {
        "path": _local("nyctaxi_sample.csv"),
        "sep": ",",
        "header": 0,
        "format": SourceFormat.CSV,
    },
    "chi_traffic_sample": {
        "path": _local("chi_traffic_sample.parquet"),
        "format": SourceFormat.PARQUET,
    },
    "fanniemae_2016Q4": {
        "path": _source("fanniemae_2016Q4.csv.gz"),
        "source": "https://ursa-qa.s3.amazonaws.com/fanniemae_loanperf/2016Q4.csv.gz",
        "sep": "|",
        "header": None,
        "format": SourceFormat.CSV,
    },
    "nyctaxi_2010-01": {
        "path": _source("nyctaxi_2010-01.csv.gz"),
        "source": "https://ursa-qa.s3.amazonaws.com/nyctaxi/yellow_tripdata_2010-01.csv.gz",
        "sep": ",",
        "header": 0,
        "format": SourceFormat.CSV,
    },
    "chi_traffic_2020_Q1": {
        "path": _source("chi_traffic_2020_Q1.parquet"),
        "source": "https://ursa-qa.s3.amazonaws.com/chitraffic/chi_traffic_2020_Q1.parquet",
        "format": SourceFormat.PARQUET,
    },
    "type_strings": {
        "path": _source("type_strings.parquet"),
        "source": "https://ursa-qa.s3.amazonaws.com/single_types/type_strings.parquet",
        "format": SourceFormat.PARQUET,
    },
    "type_dict": {
        "path": _source("type_dict.parquet"),
        "source": "https://ursa-qa.s3.amazonaws.com/single_types/type_dict.parquet",
        "format": SourceFormat.PARQUET,
    },
    "type_integers": {
        "path": _source("type_integers.parquet"),
        "source": "https://ursa-qa.s3.amazonaws.com/single_types/type_integers.parquet",
        "format": SourceFormat.PARQUET,
    },
    "type_floats": {
        "path": _source("type_floats.parquet"),
        "source": "https://ursa-qa.s3.amazonaws.com/single_types/type_floats.parquet",
        "format": SourceFormat.PARQUET,
    },
    "type_nested": {
        "path": _source("type_nested.parquet"),
        "source": "https://ursa-qa.s3.amazonaws.com/single_types/type_nested.parquet",
        "format": SourceFormat.PARQUET,
    },
    "type_simple_features": {
        "path": _source("type_simple_features.parquet"),
        "source": "https://ursa-qa.s3.amazonaws.com/single_types/type_simple_features.parquet",
        "format": SourceFormat.PARQUET,
    },
    "nyctaxi_multi_parquet_s3": {
        "download": False,
        "paths": [
            "ursa-labs-taxi-data/2009/01/data.parquet",
            "ursa-labs-taxi-data/2009/02/data.parquet",
            "ursa-labs-taxi-data/2009/03/data.parquet",
            "ursa-labs-taxi-data/2009/04/data.parquet",
        ],
        "region": "us-east-2",
        "format": SourceFormat.PARQUET,
    },
    "nyctaxi_multi_ipc_s3": {
        "download": False,
        "paths": [
            "ursa-labs-taxi-data-ipc/2013/01/data.feather",
            "ursa-labs-taxi-data-ipc/2013/02/data.feather",
            "ursa-labs-taxi-data-ipc/2013/03/data.feather",
            "ursa-labs-taxi-data-ipc/2013/04/data.feather",
        ],
        "region": "us-east-2",
        "format": SourceFormat.FEATHER,
    },
    "nyctaxi_multi_parquet_s3_sample": {
        "download": False,
        "paths": [
            "ursa-labs-taxi-data-sample/2009/02/data.parquet",
            "ursa-labs-taxi-data-sample/2009/01/data.parquet",
        ],
        "region": "us-east-2",
        "format": SourceFormat.PARQUET,
    },
    "nyctaxi_multi_ipc_s3_sample": {
        "download": False,
        "paths": [
            "ursa-labs-taxi-data-sample-ipc/2009/02/data.feather",
            "ursa-labs-taxi-data-sample-ipc/2009/01/data.feather",
        ],
        "region": "us-east-2",
        "format": SourceFormat.FEATHER,
    },
    "nyctaxi_multi_parquet_s3_repartitioned": {
        "download": False,
        "paths": [
            f"ursa-labs-taxi-data-repartitioned-10k/{year}/{month:02}/{part:04}/data.parquet"
            for year in range(2009, 2020)
            for month in range(1, 13)
            for part in range(101)
            if not (year == 2019 and month > 6)  # Data ends in 2019/06
            and not (year == 2010 and month == 3)  # Data is missing in 2010/03
        ],
        "region": "us-east-2",
        "format": SourceFormat.PARQUET,
    },
}


class Source:
    """Example source store on disk:

    data
    ├── chi_traffic_sample.parquet
    ├── fanniemae_sample.csv
    ├── nyctaxi_2010-01.csv.gz
    ├── nyctaxi_sample.csv
    └── temp
        ├── fanniemae_sample.zstd.feather
        ├── nyctaxi_2010-01.snappy.parquet
        └── nyctaxi_sample.snappy.parquet
    └── ursa-labs-taxi-data-sample
        └── 2009
            ├── 01
            │   └── data.parquet
            └── 02
                └── data.parquet
    ├── type_dict.parquet
    ├── type_floats.parquet
    └── type_integers.parquet

    Files in the "data/" folder are canonical source files used for
    benchmarking.

    Files in the "data/temp/" folder are the result of running
    benchmarks, and are derived from the canonical source files.

    If a source file isn't initially found in the data folder on disk,
    it will be downloaded from the source location (like S3) and
    placed in the data folder for subsequent benchmark runs.
    """

    def __init__(self, name):
        self.name = name
        self.store = STORE[self.name]
        self._table = None
        if self.store.get("download", True):
            self.download_source_if_not_exists()

    @property
    def tags(self):
        return {"dataset": self.name}

    @property
    def paths(self):
        return self.store.get("paths", [])

    @property
    def region(self):
        return self.store.get("region")

    @property
    def csv_parse_options(self):
        return pyarrow.csv.ParseOptions(delimiter=self.store["sep"])

    @property
    def source_path(self):
        """A path in the benchmarks data/ folder.

        For example:
            data/nyctaxi_2010-01.csv.gz
        """
        return self.store.get("path")

    @property
    def source_paths(self):
        if self.paths:
            return [_source(path) for path in self.paths]
        elif self.source_path:
            return [self.source_path]
        else:
            return []

    @property
    def format_str(self):
        return self.store.get("format").value

    def temp_path(self, file_type, compression):
        """A path in the benchmarks data/temp/ folder.

        For example:
            data/temp/nyctaxi_sample.snappy.parquet

        If the data/temp/ folder does not exist, it will be created.
        """
        pathlib.Path(temp_dir).mkdir(exist_ok=True)
        return pathlib.Path(_temp(f"{self.name}.{compression}.{file_type}"))

    def create_if_not_exists(self, file_type, compression):
        """Used to create files for benchmarking based on the canonical
        source files found in the benchmarks data folder.

        For example:
            source = _source.Source("nyctaxi_sample")
            source.create_if_not_exists("parquet", "snappy")

        Will create the following file:
            data/temp/nyctaxi_sample.snappy.parquet

        Using the following source file:
            data/nyctaxi_sample.csv
        """
        path = self.temp_path(file_type, compression)
        if not path.exists():
            if file_type == "feather":
                self._feather_write(self.table, path, compression)
            elif file_type == "parquet":
                self._parquet_write(self.table, path, compression)
        return path

    @functools.cached_property
    def dataframe(self):
        if self._table is not None:
            # this takes ~ 7 seconds for fanniemae_2016Q4
            return self.table.to_pandas()
        else:
            # this takes ~ 199 seconds for fanniemae_2016Q4
            return pandas.read_csv(
                self.store["path"],
                sep=self.store["sep"],
                header=self.store["header"],
                low_memory=False,
            )

    @functools.cached_property
    def table(self):
        path = self.temp_path("feather", "lz4")
        if path.exists():
            # this takes ~ 3 seconds for fanniemae_2016Q4
            self._table = feather.read_table(path, memory_map=False)
        else:
            # this takes ~ 205 seconds for fanniemae_2016Q4
            self._table = pyarrow.Table.from_pandas(
                self.dataframe,
                preserve_index=False,
            ).replace_schema_metadata(None)
        return self._table

    def _get_object_url(self, idx=0):
        if self.paths:
            s3_url = pathlib.Path(self.paths[idx])
            return (
                "https://"
                + s3_url.parts[0]
                + ".s3."
                + self.region
                + ".amazonaws.com/"
                + os.path.join(*s3_url.parts[1:])
            )

        return self.store.get("source")

    def download_source_if_not_exists(self):
        for idx, path in enumerate(self.source_paths):
            source_path = pathlib.Path(path)
            if not source_path.exists():
                source_path.parent.mkdir(parents=True, exist_ok=True)
                source = self.store.get("source")
                if not source:
                    source = self._get_object_url(idx)
                r = requests.get(source)
                open(source_path, "wb").write(r.content)

    def _feather_write(self, table, path, compression):
        compression = munge_compression(compression, "feather")
        feather.write_feather(table, path, compression=compression)

    def _parquet_write(self, table, path, compression):
        compression = munge_compression(compression, "parquet")
        parquet.write_table(table, path, compression=compression)
