import asyncio
import io
import os
import sys
import unittest
from unittest.mock import patch

from PIL import Image

sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

from services import overlay_service
from services.overlay_context_service import get_overlay_context_public
from services.overlay_service import OverlayCaptureRejected, ask_about_overlay_region, ask_overlay_follow_up


def _png_bytes() -> bytes:
    image = Image.new("RGB", (64, 32), color=(20, 40, 60))
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


class OverlayServiceTests(unittest.TestCase):
    def test_overlay_region_success(self):
        async def fake_generate(question: str, session_id: str = "overlay"):
            self.assertEqual(question, "What is this error?")
            self.assertEqual(session_id, "overlay-test")
            return "It appears to be a test capture, sir."

        with patch("services.llm_service.generate_response", fake_generate):
            result = asyncio.run(
                ask_about_overlay_region(
                    image_bytes=_png_bytes(),
                    question="  What is this error?  ",
                    session_id="overlay-test",
                    content_type="image/png",
                    metadata={"region_x": 1, "region_y": 2, "region_width": 64, "region_height": 32},
                )
            )

        self.assertEqual(result["reply"], "It appears to be a test capture, sir.")
        self.assertTrue(result["context_id"])
        self.assertEqual(result["image"]["mime_type"], "image/jpeg")
        self.assertEqual(result["image"]["width"], 64)

    def test_overlay_follow_up_reuses_context(self):
        calls = []

        async def fake_generate(question: str, session_id: str = "overlay"):
            calls.append((question, session_id))
            return f"reply {len(calls)}"

        with patch("services.llm_service.generate_response", fake_generate):
            first = asyncio.run(
                ask_about_overlay_region(
                    image_bytes=_png_bytes(),
                    question="Explain this",
                    session_id="overlay-test",
                )
            )
            second = asyncio.run(
                ask_overlay_follow_up(
                    context_id=first["context_id"],
                    question="What should I do next?",
                    session_id="overlay-test",
                )
            )

        self.assertEqual(second["context_id"], first["context_id"])
        self.assertEqual(second["reply"], "reply 2")
        self.assertEqual(calls[0][0], "Explain this")
        self.assertEqual(calls[1][0], "What should I do next?")
        public_context = get_overlay_context_public(first["context_id"])
        self.assertEqual(len(public_context["turns"]), 2)
        self.assertEqual(public_context["turns"][-1]["question"], "What should I do next?")

    def test_overlay_region_blocks_sensitive_window(self):
        with self.assertRaises(OverlayCaptureRejected) as raised:
            asyncio.run(
                ask_about_overlay_region(
                    image_bytes=_png_bytes(),
                    question="Explain this",
                    session_id="overlay-test",
                    metadata={"window_title": "1Password - Vault"},
                )
            )
        self.assertIn("sensitive credentials", str(raised.exception))

    def test_overlay_region_rejects_invalid_image(self):
        with self.assertRaises(OverlayCaptureRejected) as raised:
            asyncio.run(
                ask_about_overlay_region(
                    image_bytes=b"not an image",
                    question="Explain this",
                    session_id="overlay-test",
                )
            )
        self.assertIn("valid image", str(raised.exception))


    def test_overlay_maverick_direct_routing(self):
        async def fake_vision_chat(chat_history, user_message, overlay_image_b64):
            self.assertEqual(user_message, "What is this?")
            return "Mock direct Maverick response"

        from services.llm_service import generate_response
        with patch("services.llm_service._call_maverick_vision_chat", fake_vision_chat):
            reply = asyncio.run(generate_response("What is this?", session_id="overlay"))
            
        self.assertEqual(reply, "Mock direct Maverick response")


if __name__ == "__main__":
    unittest.main()
