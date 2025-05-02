# batch_ocr_analysis.py

import pytesseract
import cv2
import re
import os
import json
from PIL import Image
import numpy as np

# Setup Tesseract
pytesseract.pytesseract.tesseract_cmd = r'C:\Program Files\Tesseract-OCR\tesseract.exe'

# === OCR Functions ===

def is_readable(image, threshold=50, lang='tur'):
    data = pytesseract.image_to_data(image, lang=lang, output_type=pytesseract.Output.DICT)
    confidences = [conf for conf in data['conf'] if isinstance(conf, int) and conf != -1]
    avg_conf = sum(confidences) / len(confidences) if confidences else 0
    is_good = avg_conf >= threshold
    return is_good, avg_conf, data

def extract_text_from_image(image, lang='tur'):
    gray = cv2.cvtColor(np.array(image), cv2.COLOR_BGR2GRAY)
    _, thresh = cv2.threshold(gray, 150, 255, cv2.THRESH_BINARY)
    text = pytesseract.image_to_string(thresh, lang=lang)
    return text

def extract_total_amount(text):
    matches = re.findall(r'(?i)(toplam)[^\d]*(\d+[.,]?\d*)', text)
    if matches:
        return matches[-1][1]
    return None

# === Main Function === #
def process_all_invoices(folder_path, output_json='invoice_readability_results.json', output_vis_folder='annotated_invoices', min_conf=60):
    if not os.path.exists(output_vis_folder):
        os.makedirs(output_vis_folder)

    results = []

    for filename in os.listdir(folder_path):
        if filename.lower().endswith(('.jpg', '.jpeg', '.png')):
            image_path = os.path.join(folder_path, filename)
            try:
                pil_image = Image.open(image_path).convert("RGB")
                image = np.array(pil_image)
                image_copy = image.copy()

                is_readable_result, avg_conf, data = is_readable(pil_image, threshold=min_conf, lang='tur')
                text = extract_text_from_image(pil_image, lang='tur')
                total_amount = extract_total_amount(text)

                words_with_conf = []
                word_id_counter = 1

                for i in range(len(data['text'])):
                    word = data['text'][i]
                    conf = data['conf'][i]

                    try:
                        conf_int = int(conf)
                    except:
                        continue

                    left = data['left'][i]
                    top = data['top'][i]
                    width = data['width'][i]
                    height = data['height'][i]

                    if word.strip():
                        word_info = {
                            'id': word_id_counter,
                            'word': word,
                            'confidence': conf_int,
                            'position': {
                                'left': left,
                                'top': top,
                                'width': width,
                                'height': height
                            }
                        }
                        words_with_conf.append(word_info)

                        # Draw red box
                        cv2.rectangle(image_copy, (left, top), (left + width, top + height), (0, 0, 255), 2)

                        # Yellow overlay for low-confidence
                        if conf_int < min_conf:
                            overlay = image_copy.copy()
                            cv2.rectangle(overlay, (left, top), (left + width, top + height), (0, 255, 255), -1)
                            image_copy = cv2.addWeighted(overlay, 0.2, image_copy, 0.8, 0)

                        # Draw word ID
                        cv2.putText(
                            image_copy,
                            str(word_id_counter),
                            (left, max(top - 5, 10)),
                            cv2.FONT_HERSHEY_SIMPLEX,
                            0.5,
                            (0, 0, 0),
                            1,
                            cv2.LINE_AA
                        )

                        word_id_counter += 1

                invoice_result = {
                    'filename': filename,
                    'readable': is_readable_result,
                    'average_confidence': round(avg_conf, 2),
                    'total_amount': total_amount,
                    'sample_text': text[:300],
                    'words': words_with_conf
                }

                results.append(invoice_result)

                
                save_path = os.path.join(output_vis_folder, f"annotated_{filename}")
                cv2.imwrite(save_path, image_copy)

                print(f"✅ Processed {filename}: Readable = {is_readable_result}, Avg Conf = {avg_conf:.2f}")
            except Exception as e:
                print(f"❌ Failed to process {filename}: {e}")

    
    with open(output_json, 'w', encoding='utf-8') as f:
        json.dump(results, f, ensure_ascii=False, indent=4)

    print(f"\n📁 JSON results saved to: {output_json}")
    print(f"🖼️ Annotated images saved in: {output_vis_folder}")

# === Run ===
if __name__ == '__main__':
    invoice_folder = './invoice_data'
    process_all_invoices(invoice_folder)
