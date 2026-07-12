import logging
import tarfile
import typing as t
from pathlib import Path


class AssetError(Exception):
    """
    Raised when an asset related issue occurs.
    """

    pass


class AssetManager:
    """
    Provides easy access to the project's assets. Assets are individually
    `.tar.xz` compressed and live in the `xz_dir` directory. This class allows
    accessing them via relative paths. Whenever an asset is needed it is
    extracted first, unless it already exists in the cache.

    The asset manager is versioned, to ensure that assets of different library
    versions don't clash. Future versions may use this to delete old, unused
    assets but this is not implemented yet.
    """

    def __init__(
        self,
        xz_dir: Path,
        cache_dir: Path,
        version: str,
    ) -> None:
        # The to the directory the .xz compressed assets are located in.
        #
        # Does not have to exist, though in that case obviously no assets can be
        # loaded.
        self.xz_dir = xz_dir

        # The path to the directory where extracted assets are stored. Does not
        # need to exist.
        self.cache_dir = cache_dir

        # Will be used to version extracted assets, so that future versions
        # don't have to extract them again.
        #
        # Must only consist of characters which are valid in a path.
        self._versioned_cache_dir = cache_dir / version

    def path_to_asset(
        self,
        path: Path,
        *,
        compressed: bool = True,
    ) -> Path:
        """
        Ensures that the given asset is extracted and returns a path to it. This
        is useful for assets that are not opened with `open_asset`. If you want
        to open the file use that function instead.

        Returns a path to where the extracted asset is located.

        ## Parameters

        path: The relative path to the asset.

        compressed: Whether the asset is compressed. If it is, the function will
            ensure that the asset is extracted before returning the path.
            Uncompressed assets are returned as-is.

        ## Raises

        ValueError: If the given path is not relative.

        FileNotFoundError: If there is no asset at the given path.

        AssetError: If the given asset cannot be extracted for any reason.
        """
        # Only allow relative paths, since they're supposed to be relative to
        # the asset directory.
        if path.is_absolute():
            raise ValueError("The asset's path must be relative")

        # Compressed assets need extracting
        if compressed:
            # If the file already exists, there is nothing else to do
            extracted_path = self._versioned_cache_dir / path

            if extracted_path.exists():
                return extracted_path

            # Make sure the target directory exists
            extracted_path.parent.mkdir(parents=True, exist_ok=True)

            # Extract the file
            compressed_path = self.xz_dir / path
            compressed_path = compressed_path.with_suffix(
                compressed_path.suffix + ".tar.xz"
            )

            logging.debug(f"Extracting asset `{path}` to `{extracted_path}`")

            try:
                with tarfile.open(compressed_path, "r:xz") as tar:
                    tar.extractall(extracted_path.parent)

            except FileNotFoundError:
                raise FileNotFoundError(f"There is no asset at `{path}`")

            except tarfile.TarError as e:
                raise AssetError(
                    f"Could not extract the asset from `{path}`: {e}"
                ) from e

            except OSError as e:
                raise AssetError(
                    f"Could not read the asset file at `{path}`: {e}"
                ) from e

        # Uncompressed can be used as-is
        elif not (self.xz_dir / path).exists():
            raise FileNotFoundError(f"There is no asset at `{path}`")

        # Done
        return extracted_path

    @t.overload
    def open_asset(
        self,
        path: Path,
        mode: t.Literal["r"],
        *,
        compressed: bool = True,
    ) -> t.IO[str]: ...

    @t.overload
    def open_asset(
        self,
        path: Path,
        mode: t.Literal["rb"],
        *,
        compressed: bool = True,
    ) -> t.IO[bytes]: ...

    def open_asset(
        self,
        path: Path,
        mode: t.Literal["r", "rb"] = "r",
        *,
        compressed: bool = True,
    ) -> t.IO:
        """
        Opens an asset file for reading.

        Returns a file-like object.

        ## Parameters

        path: The relative path to the asset.

        mode: The mode to open the file in. The default is `"r"`.

        compressed: Whether the asset is compressed. If it is, the function will
            ensure that the asset is extracted before opening it. Uncompressed
            assets are opened as-is.

        ## Raises

        ValueError: If the given path is not relative.

        FileNotFoundError: If there is no asset at the given path.

        AssetError: If the asset cannot be opened for any reason.
        """
        # Make sure the file exists.
        extracted_path = self.path_to_asset(
            path=path,
            compressed=compressed,
        )

        # The file exists now - open it.
        return extracted_path.open(mode)

    def get_cache_path(self, path: Path) -> Path:
        """
        Returns where the manager would cache the extracted path, if it was to
        be extracted. This does not actually extract anything, nor does it check
        whether the archive for this asset exists.

        You can use this function if you want to dump your own cached files in
        the asset manager's cache directory.

        After this function returns, the parent directory of the returned path
        will exist.

        ## Raises

        ValueError: If the given path is not relative.

        AssetError: If the containing directory of the returned path could not
            be created.
        """
        # Only allow relative paths, since they're supposed to be relative to
        # the asset directory.
        if path.is_absolute():
            raise ValueError("The asset's path must be relative")

        # Build the result path
        result = self._versioned_cache_dir / path

        # Make sure the parent directory exists
        try:
            result.parent.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            raise AssetError(
                f"Could not create the containing directory of `{result}`: {e}"
            ) from e

        # Done
        return result
