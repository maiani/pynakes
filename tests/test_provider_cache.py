"""Provider-response cache tests."""

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from pynakes.provider_cache import ProviderCache, open_cache


class TestStore:
    def test_round_trips_a_response(self, tmp_path: Path) -> None:
        cache = ProviderCache(tmp_path / ".pynakes-cache")
        cache.put("doi", "10.5555/example", "bib", "@article{a}")

        assert cache.get("doi", "10.5555/example", "bib") == "@article{a}"
        assert cache.get("doi", "10.5555/example", "json") is None
        assert cache.get("arxiv", "10.5555/example", "bib") is None

    def test_identifier_lookup_is_case_insensitive(self, tmp_path: Path) -> None:
        cache = ProviderCache(tmp_path / ".pynakes-cache")
        cache.put("doi", "10.5555/Example", "bib", "@article{a}")

        assert cache.get("doi", "10.5555/example", "bib") == "@article{a}"

    def test_the_whole_cache_is_one_file(self, tmp_path: Path) -> None:
        # The point of the consolidated store: an online run adds one path to
        # the user's folder no matter how many identifiers it looks up.
        cache = ProviderCache(tmp_path / ".pynakes-cache")
        for index in range(25):
            cache.put("doi", f"10.5555/example-{index}", "bib", f"@article{{a{index}}}")

        assert sorted(item.name for item in tmp_path.iterdir()) == [".pynakes-cache"]
        assert (tmp_path / ".pynakes-cache").is_file()

    def test_records_survive_a_reload(self, tmp_path: Path) -> None:
        path = tmp_path / ".pynakes-cache"
        ProviderCache(path).put("doi", "10.5555/example", "bib", "@article{a}")

        assert ProviderCache(path).get("doi", "10.5555/example", "bib") == "@article{a}"

    def test_a_later_record_supersedes_an_earlier_one(self, tmp_path: Path) -> None:
        path = tmp_path / ".pynakes-cache"
        cache = ProviderCache(path)
        cache.put("doi", "10.5555/example", "bib", "@article{old}")
        cache.put("doi", "10.5555/example", "bib", "@article{new}")

        assert ProviderCache(path).get("doi", "10.5555/example", "bib") == "@article{new}"

    def test_storing_an_unchanged_body_appends_nothing(self, tmp_path: Path) -> None:
        path = tmp_path / ".pynakes-cache"
        cache = ProviderCache(path)
        cache.put("doi", "10.5555/example", "bib", "@article{a}")
        first = path.read_text(encoding="utf-8")
        cache.put("doi", "10.5555/example", "bib", "@article{a}")

        assert path.read_text(encoding="utf-8") == first

    def test_a_truncated_final_line_is_skipped(self, tmp_path: Path) -> None:
        # The only tear a single append can leave. A cache miss is recoverable,
        # so the good records must still load rather than the file raising.
        path = tmp_path / ".pynakes-cache"
        cache = ProviderCache(path)
        cache.put("doi", "10.5555/kept", "bib", "@article{kept}")
        with path.open("a", encoding="utf-8") as handle:
            handle.write('{"namespace": "doi", "id": "10.5555/torn", "form')

        reloaded = ProviderCache(path)
        assert reloaded.get("doi", "10.5555/kept", "bib") == "@article{kept}"
        assert reloaded.get("doi", "10.5555/torn", "bib") is None

    def test_compaction_keeps_live_records_and_shrinks_the_file(self, tmp_path: Path) -> None:
        path = tmp_path / ".pynakes-cache"
        cache = ProviderCache(path)
        for index in range(60):
            cache.put("doi", "10.5555/example", "bib", f"@article{{a{index}}}")

        assert len(path.read_text(encoding="utf-8").splitlines()) < 60
        assert cache.get("doi", "10.5555/example", "bib") == "@article{a59}"
        assert ProviderCache(path).get("doi", "10.5555/example", "bib") == "@article{a59}"

    def test_drop_forgets_one_response(self, tmp_path: Path) -> None:
        path = tmp_path / ".pynakes-cache"
        cache = ProviderCache(path)
        cache.put("doi", "10.5555/bad", "bib", "not bibtex")
        cache.put("doi", "10.5555/good", "bib", "@article{a}")

        assert cache.drop("doi", "10.5555/bad", "bib") is True
        assert cache.drop("doi", "10.5555/bad", "bib") is False
        assert ProviderCache(path).get("doi", "10.5555/bad", "bib") is None
        assert ProviderCache(path).get("doi", "10.5555/good", "bib") == "@article{a}"

    def test_clear_removes_the_file(self, tmp_path: Path) -> None:
        path = tmp_path / ".pynakes-cache"
        cache = ProviderCache(path)
        cache.put("doi", "10.5555/example", "bib", "@article{a}")

        assert cache.clear() == 1
        assert not path.exists()
        assert cache.get("doi", "10.5555/example", "bib") is None

    def test_stats_report_what_is_held(self, tmp_path: Path) -> None:
        cache = ProviderCache(tmp_path / ".pynakes-cache")
        cache.put("doi", "10.5555/example", "bib", "@article{a}")
        cache.put("arxiv", "1234.5678", "xml", "<feed/>")

        stats = cache.stats()
        assert stats["records"] == 2
        assert stats["exists"] is True
        assert stats["namespaces"] == {"arxiv": 1, "doi": 1}

    def test_stats_on_a_cache_that_was_never_written(self, tmp_path: Path) -> None:
        stats = ProviderCache(tmp_path / ".pynakes-cache").stats()

        assert stats == {
            "path": str(tmp_path / ".pynakes-cache"),
            "exists": False,
            "records": 0,
            "bytes": 0,
            "namespaces": {},
        }

    def test_dropping_the_last_record_removes_the_file(self, tmp_path: Path) -> None:
        path = tmp_path / ".pynakes-cache"
        cache = ProviderCache(path)
        cache.put("doi", "10.5555/example", "bib", "@article{a}")
        cache.drop("doi", "10.5555/example", "bib")

        assert not path.exists()


class TestLocationResolution:
    def test_a_path_is_taken_as_the_cache_file(self, tmp_path: Path) -> None:
        cache = open_cache(tmp_path / "responses")
        cache.put("doi", "10.5555/example", "bib", "@article{a}")

        assert cache.path == tmp_path / "responses"
        assert (tmp_path / "responses").is_file()

    def test_no_location_memoizes_without_touching_disk(self, tmp_path: Path) -> None:
        # No --cache-file is not "no cache": it is a memo that writes nothing, so
        # one run still asks a provider about a given identifier only once.
        cache = open_cache(None)
        cache.put("doi", "10.5555/example", "bib", "@article{a}")

        assert cache.path is None
        assert cache.get("doi", "10.5555/example", "bib") == "@article{a}"
        assert open_cache(None) is cache
        assert list(tmp_path.iterdir()) == []

    def test_the_in_process_memo_reports_itself_as_holding_no_file(self) -> None:
        cache = open_cache(None)
        cache.put("doi", "10.5555/example", "bib", "@article{a}")

        stats = cache.stats()
        assert stats["path"] is None
        assert stats["exists"] is False
        assert stats["bytes"] == 0
        assert stats["records"] == 1

    def test_the_in_process_memo_survives_compaction_pressure(self) -> None:
        # Compaction is a file operation; with no file it must be a no-op that
        # still keeps every live record reachable.
        cache = open_cache(None)
        for index in range(60):
            cache.put("doi", f"10.5555/example-{index}", "bib", f"@a{{{index}}}")

        assert cache.get("doi", "10.5555/example-59", "bib") == "@a{59}"
        assert cache.stats()["records"] == 60

    def test_one_instance_is_shared_per_path(self, tmp_path: Path) -> None:
        # A single online run reads the cache file once, not once per lookup.
        assert open_cache(tmp_path / "c") is open_cache(tmp_path / "c")

    def test_a_directory_is_rejected_rather_than_written_into(self, tmp_path: Path) -> None:
        # --cache-file names a file. Silently creating something inside a
        # directory the caller named would hide where the cache actually went.
        target = tmp_path / "somewhere"
        target.mkdir()

        with pytest.raises(ValueError, match="not a file"):
            open_cache(target)

    def test_a_path_whose_parent_does_not_exist_yet_is_created_on_write(
        self, tmp_path: Path
    ) -> None:
        path = tmp_path / "build" / "cache.jsonl"
        cache = open_cache(path)
        cache.put("doi", "10.5555/example", "bib", "@article{a}")

        assert path.is_file()
        assert ProviderCache(path).get("doi", "10.5555/example", "bib") == "@article{a}"

    def test_an_unsupported_format_is_rejected(self, tmp_path: Path) -> None:
        cache = ProviderCache(tmp_path / ".cache")

        with pytest.raises(ValueError, match="Unsupported provider cache format"):
            cache.get("doi", "10.5555/example", "csv")


class TestConcurrency:
    """``verify``/``enrich --concurrency`` can call into one cache from several threads."""

    def test_concurrent_puts_do_not_corrupt_the_file(self, tmp_path: Path) -> None:
        # 200 puts against a compaction threshold this low (see
        # _COMPACT_FACTOR/_COMPACT_SLACK) guarantees several compactions —
        # the file-rewriting path most exposed to a missing lock — happen
        # while other threads are still appending.
        path = tmp_path / ".pynakes-cache"
        cache = ProviderCache(path)

        def store(index: int) -> None:
            cache.put("doi", f"10.5555/example-{index}", "bib", f"@article{{a{index}}}")

        with ThreadPoolExecutor(max_workers=8) as executor:
            list(executor.map(store, range(200)))

        reloaded = ProviderCache(path)
        for index in range(200):
            assert reloaded.get("doi", f"10.5555/example-{index}", "bib") == f"@article{{a{index}}}"

    def test_concurrent_open_cache_returns_one_shared_instance(self, tmp_path: Path) -> None:
        path = tmp_path / ".pynakes-cache"

        def open_it(_: int) -> ProviderCache:
            return open_cache(path)

        with ThreadPoolExecutor(max_workers=8) as executor:
            instances = list(executor.map(open_it, range(16)))

        assert len({id(instance) for instance in instances}) == 1
