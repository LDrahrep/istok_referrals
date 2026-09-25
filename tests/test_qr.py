from PIL import ImageFilter

from referrals.qr import decode_emp_id
from tests.qr_images import blank_photo_jpeg, in_scene, qr_image, qr_photo_jpeg, to_bytes

EMP = "EMP-7b682ed0-2485-44fe-a727-d40f8d7e0f42"


def test_decodes_clean_png():
    assert decode_emp_id(to_bytes(qr_image(EMP), "PNG")) == EMP


def test_decodes_phone_photo():
    assert decode_emp_id(qr_photo_jpeg(EMP)) == EMP


def test_decodes_small_qr_in_big_frame():
    assert decode_emp_id(to_bytes(in_scene(qr_image(EMP, 150)))) == EMP


def test_decodes_rotated():
    assert decode_emp_id(to_bytes(in_scene(qr_image(EMP)).rotate(35, fillcolor=150))) == EMP


def test_decodes_blurred():
    assert decode_emp_id(to_bytes(in_scene(qr_image(EMP)).filter(ImageFilter.GaussianBlur(2)))) == EMP


def test_normalizes_uppercase_id():
    assert decode_emp_id(qr_photo_jpeg(EMP.upper())) == EMP


def test_ignores_qr_with_other_text():
    assert decode_emp_id(qr_photo_jpeg("https://example.com")) is None


def test_photo_without_qr():
    assert decode_emp_id(blank_photo_jpeg()) is None


def test_garbage_bytes():
    assert decode_emp_id(b"not an image") is None


def test_empty_bytes():
    assert decode_emp_id(b"") is None
