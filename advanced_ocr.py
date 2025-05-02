import os
import pandas as pd
import cv2
import pytesseract
from pytesseract import Output
import numpy as np

# Tesseract
pytesseract.pytesseract.tesseract_cmd = r'C:\Program Files\Tesseract-OCR\tesseract.exe'

# Excel writer
writer = pd.ExcelWriter('invoice_output.xlsx', engine='xlsxwriter')

# data processing & OCR function
def process_ocr_data(image):

    data = pytesseract.image_to_data(image, output_type=Output.DATAFRAME)
    data = data[data['text'].notna() & (data['text'].str.strip() != '')]
    data = data.reset_index(drop=True)
    data['ocr_id'] = data.index
    data = data.sort_values(by='ocr_id').reset_index(drop=True)
    
    # add extra columns for layout analysis
    data['bottom'] = data['top'] + data['height']
    data['end'] = data['left'] + data['width']
    data['end - left'] = data['left'].shift(-1) - data['end']
    
    return data

# Function to assign groups based on the layout analysis
def assign_groups(data):
    groups = []
    group_id = 0

    for i in range(len(data)):
        if i == 0:
            groups.append(group_id)
            continue

        prev_bottom = data.loc[i - 1, 'bottom']
        curr_top = data.loc[i, 'top']

        if curr_top <= prev_bottom:
            
            groups.append(group_id)
        else:

            group_id += 1
            groups.append(group_id)

    data['group'] = groups
    return data


amount_keywords = ['toplam', 'aratoplam', 'toplam tutar', 'vergi', 'odenecek tutar']

# Function to find the nearest value to a keyword in the group
def find_nearest_value(group_data, keyword, threshold=50):
    
    keyword_rows = group_data[group_data['text'].str.contains(keyword, case=False, na=False)]
    
    
    if keyword_rows.empty:
        return None

    closest_value = None
    closest_distance = float('inf')

    for _, row in keyword_rows.iterrows():
        keyword_x1, keyword_y1 = row['left'], row['top']

        
        for _, num_row in group_data.iterrows():
            if num_row['text'].replace('.', '', 1).isdigit():  
                num_x1, num_y1 = num_row['left'], num_row['top']
                # Calculate the distance between the keyword and the number
                distance = np.sqrt((num_x1 - keyword_x1)**2 + (num_y1 - keyword_y1)**2)
                
                if distance < closest_distance and distance <= threshold:
                    closest_value = num_row['text']
                    closest_distance = distance

    return closest_value

# Function to assign final groups based on the layout analysis and nearest values
def assign_final_groups(data): 

    filtered_vals = sorted(data['end - left'].dropna())
    max_val = max(filtered_vals)
    filtered_vals = [val for val in filtered_vals if 0 <= val <= 100]
    
    
    max_jump = 0
    prev_value = None

    for i in range(len(filtered_vals) - 1):
        diff = filtered_vals[i + 1] - filtered_vals[i]
        if diff > max_jump:
            max_jump = diff
            prev_value = filtered_vals[i]
    
  
    data['final_group'] = -1  
    new_group_id = 0

    
    for group_id in sorted(data['group'].unique()):
        group_data = data[data['group'] == group_id].copy().reset_index()
        
        current_final_group = new_group_id
        data.loc[group_data.loc[0, 'index'], 'final_group'] = current_final_group

        for i in range(1, len(group_data)):
            prev_row_idx = group_data.loc[i - 1, 'index']
            curr_row_idx = group_data.loc[i, 'index']
            
            if data.loc[prev_row_idx, 'end - left'] > prev_value:
                new_group_id += 1
                current_final_group = new_group_id

            data.loc[curr_row_idx, 'final_group'] = current_final_group

        new_group_id += 1  

    # assigning the nearest values
    amount_keywords = ['toplam', 'aratoplam', 'toplam tutar', 'vergi', 'odenecek tutar']
    
    data['amount_value'] = None 

    for final_group in sorted(data['final_group'].unique()):
        group_data = data[data['final_group'] == final_group].copy()

        for keyword in amount_keywords:
            nearest_value = find_nearest_value(group_data, keyword)
            if nearest_value:
                
                data.loc[data['final_group'] == final_group, 'amount_value'] = nearest_value
                break  

    # Remove unnecessary ones
    cols = ['left', 'top', 'bottom', 'end', 'conf', 'text', 'final_group', 'amount_value']
    data = data[cols] 
    # Data aggregation
    final_group_data = data.groupby('final_group').agg({
        'left': 'min',       # Minimum 'left' value for each group
        'top': 'min',        # Minimum 'top' value for each group
        'bottom': 'max',     # Maximum 'bottom' value for each group
        'end': 'max',        # Maximum 'end' value for each group
        'conf': 'mean',      # Average confidence for the group
        'text': ' '.join,    # Concatenate text for the group
        'amount_value': 'first'  # Get the first value (since it's the same for the group)
    }).reset_index()

    return final_group_data

def write_to_excel(final_group_data, file_name, output_file):
    """
    Writing the final grouped data to an Excel file.
    Parameters:
    final_group_data (DataFrame): The DataFrame containing the grouped and aggregated data.
    file_name (str): The name of the file to be used for the sheet name in the Excel file.
    output_file (str): The path of the Excel file where data will be saved.
    """
    with pd.ExcelWriter(output_file, engine='xlsxwriter') as writer:
       
        sheet_name = f"{file_name}"
        final_group_data.to_excel(writer, sheet_name=sheet_name, index=False)
        
        
        worksheet = writer.sheets[sheet_name]
        
        
        worksheet.add_table(0, 0, len(final_group_data), len(final_group_data.columns) - 1,
                            {'columns': [{'header': col} for col in final_group_data.columns]})

    print(f"Data has been successfully written to {output_file}")
 
def draw_rectangles_on_image(image, data, file_name):
    """
    Drawing rectangles on the image based on the final groups and annotate with group IDs.
    Parameters:
    image (ndarray): The image on which to draw rectangles (should be a numpy array from OpenCV).
    data (DataFrame): The DataFrame containing the 'final_group' and the position data ('left', 'top', 'end', 'bottom').
    file_name (str): The file name used to save the annotated image.
    """
    
    for final_id, group_df in data.groupby('final_group'):
        x1 = int(group_df['left'].min())
        y1 = int(group_df['top'].min())
        x2 = int(group_df['end'].max())
        y2 = int(group_df['bottom'].max())
        
        
        cv2.rectangle(image, (x1, y1), (x2, y2), (0, 255, 0), 2)  # Green rectangle
        
        
        cv2.putText(image, f'Group {final_id}', (x1, y1 - 10),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 255), 1)  # Red text
    
    
    output_img_path = f'./invoice_data/annotated_invoices/{file_name}_annotated.jpg'
    cv2.imwrite(output_img_path, image)
    
    print(f"Annotated image saved as {output_img_path}")


invoice_folder = './invoice_data'
invoice_files = [f for f in os.listdir(invoice_folder) if f.endswith('.jpg') or f.endswith('.png')]

for idx, file_name in enumerate(invoice_files):
    image_path = os.path.join(invoice_folder, file_name)
    image = cv2.imread(image_path)

    # Process the OCR data and get the DataFrame
    print(f"Processing file {idx + 1}/{len(invoice_files)}: {file_name}")
    processed_data = process_ocr_data(image)
    grouped_data = assign_groups(processed_data)

    final_data = assign_final_groups(grouped_data)
    write_to_excel(final_data, file_name, 'invoice_output.xlsx')
    draw_rectangles_on_image(image, final_data, file_name)
    
print("All files processed and Excel file created.")


# python advanced_ocr.py
