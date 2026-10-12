"""No network or action tools: bounded PDF/image/JSON parsing in a disposable process."""

import base64
import hashlib
import io
import math
import multiprocessing
import os
import time


class ParseFailure(Exception):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def parse(content, mime, attachment_id, options, strategy="AUTO"):
    from PIL import Image, ImageOps

    from . import native, structured

    max_pixels = options.get("max_image_pixels", 25000000)
    Image.MAX_IMAGE_PIXELS = max_pixels
    metadata = {
        "attachment_id": attachment_id,
        "server_sha256": hashlib.sha256(content).hexdigest(),
        "original_name": options.get("original_name"),
        "detected_content_type": mime,
        "size_bytes": len(content),
        "page_count": None,
        "image_width_px": None,
        "image_height_px": None,
        "embedded_created_at_raw": None,
        "embedded_modified_at_raw": None,
        "pdf_creator": None,
        "pdf_producer": None,
        "encrypted": False,
        "has_javascript": False,
        "embedded_file_count": 0,
        "signature_field_count": 0,
        "metadata_warnings": [],
    }
    pages, lines, tokens, qr = [], [], {}, []
    canonical, observations = native.empty(), []
    text, method, engine_kind, error = "", "NATIVE_TEXT", "RULES", None

    def image_page(image, number, transform):
        if image.width * image.height > options.get("max_render_pixels", 10000000):
            raise ParseFailure("DOCUMENT_LIMIT_EXCEEDED")
        converted = image.convert("RGB")
        buffer = io.BytesIO()
        converted.save(buffer, format="PNG")
        page = {
            "page_number": number,
            "image": base64.b64encode(buffer.getvalue()).decode(),
            "width_px": converted.width,
            "height_px": converted.height,
            "transformation_json": transform,
        }
        pages.append(page)
        try:
            import zxingcpp

            for barcode in zxingcpp.read_barcodes(converted):
                if len(barcode.text) > 20000:
                    raise ParseFailure("DOCUMENT_LIMIT_EXCEEDED")
                position = barcode.position
                xs = [
                    position.top_left.x,
                    position.top_right.x,
                    position.bottom_left.x,
                    position.bottom_right.x,
                ]
                ys = [
                    position.top_left.y,
                    position.top_right.y,
                    position.bottom_left.y,
                    position.bottom_right.y,
                ]
                qr.append(
                    {
                        "payload": barcode.text,
                        "page_number": number,
                        "bounding_box": {
                            "x0": max(0, min(xs) / converted.width),
                            "x1": min(1, max(xs) / converted.width),
                            "y0": max(0, min(ys) / converted.height),
                            "y1": min(1, max(ys) / converted.height),
                        },
                    }
                )
        except ImportError:
            metadata["metadata_warnings"].append("QR_DECODER_UNAVAILABLE")
        return converted

    if mime == "application/pdf":
        if not content.startswith(b"%PDF-"):
            raise ParseFailure("FILE_SIGNATURE_MISMATCH")
        import pdfplumber
        import pypdfium2 as pdfium
        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(content))
        if reader.is_encrypted:
            raise ParseFailure("DOCUMENT_ENCRYPTED")
        count = len(reader.pages)
        if count > options.get("max_pages", 100):
            raise ParseFailure("DOCUMENT_LIMIT_EXCEEDED")
        metadata["page_count"] = count
        info = reader.metadata or {}
        for source, target in {
            "/CreationDate": "embedded_created_at_raw",
            "/ModDate": "embedded_modified_at_raw",
            "/Creator": "pdf_creator",
            "/Producer": "pdf_producer",
        }.items():
            metadata[target] = str(info[source])[:1000] if info.get(source) else None
        names = reader.root_object.get("/Names", {})
        names = names.get_object() if hasattr(names, "get_object") else names
        metadata["has_javascript"] = bool(
            names.get("/JavaScript") or reader.root_object.get("/OpenAction")
        )
        embedded = names.get("/EmbeddedFiles", {})
        embedded = embedded.get_object() if hasattr(embedded, "get_object") else embedded
        metadata["embedded_file_count"] = len(embedded.get("/Names", [])) // 2
        metadata["signature_field_count"] = sum(
            1 for f in (reader.get_fields() or {}).values() if f.get("/FT") == "/Sig"
        )
        if metadata["has_javascript"] or metadata["embedded_file_count"]:
            metadata["metadata_warnings"].append(
                "Active/embedded content is retained only in the original; never executed."
            )
        document = pdfium.PdfDocument(content)
        try:
            with pdfplumber.open(io.BytesIO(content)) as pdf:
                for index, p in enumerate(pdf.pages):
                    page = document[index]
                    width, height = page.get_size()
                    if width <= 0 or height <= 0:
                        raise ParseFailure("FILE_SIGNATURE_MISMATCH")
                    scale = min(
                        1.6,
                        math.sqrt(options.get("max_render_pixels", 10000000) / (width * height)),
                    )
                    bitmap = page.render(scale=scale)
                    try:
                        image_page(
                            bitmap.to_pil(),
                            index + 1,
                            {
                                "scale": scale,
                                "rotation": p.rotation,
                                "coordinate_space": "RENDERED_PAGE_TOP_LEFT",
                            },
                        )
                    finally:
                        bitmap.close()
                        page.close()
                    for line in p.extract_text_lines():
                        raw = line["text"]
                        start = len(text)
                        text += raw + "\n"
                        if len(text) > options.get("max_text", 1000000):
                            raise ParseFailure("DOCUMENT_LIMIT_EXCEEDED")
                        lines.append(
                            {
                                "text": raw,
                                "locator": {
                                    "source_attachment_id": attachment_id,
                                    "page_number": index + 1,
                                    "coordinate_space": "RENDERED_PAGE_TOP_LEFT",
                                    "bounding_box": {
                                        "x0": max(0, line["x0"] / p.width),
                                        "x1": min(1, line["x1"] / p.width),
                                        "y0": max(0, line["top"] / p.height),
                                        "y1": min(1, line["bottom"] / p.height),
                                    },
                                    "text_start": start,
                                    "text_end": start + len(raw),
                                },
                            }
                        )
        finally:
            document.close()
    elif mime in {"image/png", "image/jpeg"}:
        expected = b"\x89PNG\r\n\x1a\n" if mime == "image/png" else b"\xff\xd8\xff"
        if not content.startswith(expected):
            raise ParseFailure("FILE_SIGNATURE_MISMATCH")
        with Image.open(io.BytesIO(content)) as source:
            if source.width * source.height > max_pixels:
                raise ParseFailure("DOCUMENT_LIMIT_EXCEEDED")
            metadata.update(
                image_width_px=source.width, image_height_px=source.height, page_count=1
            )
            source.verify()
        with Image.open(io.BytesIO(content)) as source:
            oriented = ImageOps.exif_transpose(source)
            image_page(
                oriented,
                1,
                {"orientation": "EXIF_TRANSPOSE", "coordinate_space": "RENDERED_PAGE_TOP_LEFT"},
            )
    elif mime == "application/json":
        try:
            canonical, observations, tokens = structured.parse(content, attachment_id)
        except (ValueError, UnicodeError, KeyError) as exc:
            raise ParseFailure("UNSUPPORTED_STRUCTURED_PROFILE") from exc
        engine_kind, method = "STRUCTURED_JSON", "STRUCTURED_JSON"
    else:
        raise ParseFailure("FILE_SIGNATURE_MISMATCH")

    if mime != "application/json" and (strategy == "OCR" or not text.strip()):
        if (
            strategy == "SIMULATION_FIXTURE"
            and options.get("simulation_fixture")
            and options.get("execution_mode") == "SIMULATION"
        ):
            fixture = options["simulation_fixture"]
            lines, text = [], ""
            for row in fixture["lines"]:
                start = len(text)
                text += row["text"] + "\n"
                lines.append(
                    {
                        "text": row["text"],
                        "method": "OCR",
                        "confidence": row.get("confidence"),
                        "locator": {
                            "source_attachment_id": attachment_id,
                            "page_number": 1,
                            "coordinate_space": "RENDERED_PAGE_TOP_LEFT",
                            "bounding_box": row["bounding_box"],
                            "text_start": start,
                            "text_end": start + len(row["text"]),
                        },
                    }
                )
            engine_kind, method = "SIMULATION_FIXTURE", "OCR"
        elif options.get("ocr_engine") == "tesseract" and strategy != "NATIVE_TEXT":
            import pytesseract

            try:
                for page in pages:
                    image = Image.open(io.BytesIO(base64.b64decode(page["image"])))
                    data = pytesseract.image_to_data(
                        image, output_type=pytesseract.Output.DICT, timeout=60
                    )
                    grouped = {}
                    for i, word in enumerate(data["text"]):
                        if word.strip():
                            key = (data["block_num"][i], data["par_num"][i], data["line_num"][i])
                            grouped.setdefault(key, []).append(i)
                    for indices in grouped.values():
                        raw = " ".join(data["text"][i] for i in indices)
                        start = len(text)
                        text += raw + "\n"
                        xs = [data["left"][i] for i in indices]
                        ys = [data["top"][i] for i in indices]
                        scores = [
                            float(data["conf"][i])
                            for i in indices
                            if 0 <= float(data["conf"][i]) <= 100
                        ]
                        confidence = sum(scores) / len(scores) / 100 if scores else None
                        lines.append(
                            {
                                "text": raw,
                                "method": "OCR",
                                "confidence": confidence,
                                "locator": {
                                    "source_attachment_id": attachment_id,
                                    "page_number": page["page_number"],
                                    "coordinate_space": "RENDERED_PAGE_TOP_LEFT",
                                    "bounding_box": {
                                        "x0": min(xs) / image.width,
                                        "y0": min(ys) / image.height,
                                        "x1": max(
                                            data["left"][i] + data["width"][i] for i in indices
                                        )
                                        / image.width,
                                        "y1": max(
                                            data["top"][i] + data["height"][i] for i in indices
                                        )
                                        / image.height,
                                    },
                                    "text_start": start,
                                    "text_end": start + len(raw),
                                },
                            }
                        )
                engine_kind, method = "OCR", "OCR"
            except (pytesseract.TesseractNotFoundError, RuntimeError):
                error = "OCR_UNAVAILABLE"
        else:
            error = "OCR_UNAVAILABLE" if strategy != "NATIVE_TEXT" else "NATIVE_TEXT_UNAVAILABLE"
    if (
        len(text) > options.get("max_text", 1000000)
        or sum(len(p["image"]) for p in pages) > 40 * 1024 * 1024
    ):
        raise ParseFailure("DOCUMENT_LIMIT_EXCEEDED")
    if mime != "application/json":
        canonical, observations = native.parse(lines, options["text_artifact_id"])
    if options.get("document_type") == "OTHER":
        canonical = {
            **native.empty(),
            "header": {
                k: v
                for k, v in canonical["header"].items()
                if k in {"document_number", "issue_date"}
            },
        }
        observations = [
            o
            for o in observations
            if o["field_path"] in {"header.document_number", "header.issue_date"}
        ]
    return {
        "canonical_document": canonical,
        "observations": observations,
        "pages": pages,
        "metadata": metadata,
        "text": text,
        "text_method": method,
        "signed_tokens": tokens,
        "qr_payloads": qr,
        "engine_kind": engine_kind,
        "engine_name": "TradeTwin native/structured capture"
        if engine_kind == "RULES"
        else engine_kind,
        "engine_version": "PH3_CAPTURE_V1",
        "status": "PARTIAL" if error else "SUCCEEDED",
        "error_code": error,
    }


def child(connection, content, mime, attachment_id, options, strategy):
    try:
        # Document bytes never receive network access, tools, credentials, or executable privileges.
        for key in list(os.environ):
            if any(secret in key for secret in ("TOKEN", "SECRET", "KEY", "PASSWORD")):
                os.environ.pop(key, None)
        try:
            import resource

            memory = options.get("memory_bytes", 512 * 1024 * 1024)
            resource.setrlimit(resource.RLIMIT_AS, (memory, memory))
            resource.setrlimit(resource.RLIMIT_CPU, (300, 300))
        except ImportError:
            pass
        import socket

        def deny(*args, **kwargs):
            raise OSError("Parser network access is disabled")

        class NetworkDisabledSocket(socket.socket):
            def connect(self, *args, **kwargs):
                return deny(*args, **kwargs)

            def connect_ex(self, *args, **kwargs):
                return deny(*args, **kwargs)

        socket.create_connection = deny
        socket.socket = NetworkDisabledSocket
        connection.send((True, parse(content, mime, attachment_id, options, strategy)))
    except ParseFailure as exc:
        connection.send((False, exc.code))
    except MemoryError:
        connection.send((False, "DOCUMENT_LIMIT_EXCEEDED"))
    except Exception:
        connection.send((False, "DOCUMENT_PARSE_FAILED"))
    finally:
        connection.close()


def isolated_parse(content, mime, attachment_id, options, strategy="AUTO"):
    if len(content) > 20 * 1024 * 1024:
        raise ParseFailure("DOCUMENT_LIMIT_EXCEEDED")
    context = multiprocessing.get_context("spawn")
    receiving, sending = context.Pipe(duplex=False)
    process = context.Process(
        target=child, args=(sending, content, mime, attachment_id, options, strategy)
    )
    process.start()
    sending.close()
    deadline = time.monotonic() + options.get("timeout_seconds", 300)
    try:
        while time.monotonic() < deadline:
            if receiving.poll(0.2):
                try:
                    success, output = receiving.recv()
                except EOFError as exc:
                    raise ParseFailure("DOCUMENT_PARSE_FAILED") from exc
                if not success:
                    raise ParseFailure(output)
                return output
            if not process.is_alive():
                raise ParseFailure("DOCUMENT_PARSE_FAILED")
        raise ParseFailure("STAGE_TIMEOUT")
    finally:
        receiving.close()
        if process.is_alive():
            process.terminate()
        process.join(timeout=5)
        if process.is_alive():
            process.kill()
            process.join()
