import qrcode
from qrcode.constants import ERROR_CORRECT_H
from PIL import Image

def generate_qr_with_logo(url, logo_path, output_path, logo_ratio=0.2):
    # Create QR code
    qr = qrcode.QRCode(
        version=None,
        error_correction=ERROR_CORRECT_H,  # High error correction for logo overlay
        box_size=10,
        border=4,
    )
    qr.add_data(url)
    qr.make(fit=True)
    qr_img = qr.make_image(fill_color="black", back_color="white").convert("RGBA")

    # Open and resize logo
    logo = Image.open(logo_path).convert("RGBA")
    qr_width, qr_height = qr_img.size
    max_logo_size = int(min(qr_width, qr_height) * logo_ratio)
    logo.thumbnail((max_logo_size, max_logo_size), Image.Resampling.LANCZOS)

    # Position logo at center
    logo_pos = ((qr_width - logo.width) // 2, (qr_height - logo.height) // 2)
    qr_img.paste(logo, logo_pos, logo)

    # Save final QR code
    qr_img.save(output_path)
    print(f"QR code saved to {output_path}")

if __name__ == "__main__":
    generate_qr_with_logo(
        url="https://affiliate.agroverse.shop/",
        logo_path="agroverse_logo.jpg",   # Path to your logo
        output_path="affiliate_qr.png"
    )
