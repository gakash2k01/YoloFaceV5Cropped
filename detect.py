# -*- coding: UTF-8 -*-
import argparse
import time
from pathlib import Path

import cv2
import torch
import torch.backends.cudnn as cudnn
from numpy import random
import copy
from PIL import Image
# from google.colab.patches import cv2_imshow

from models.experimental import attempt_load
from utils.datasets import letterbox
from utils.general import check_img_size, non_max_suppression_face, apply_classifier, scale_coords, xyxy2xywh, \
    strip_optimizer, set_logging, increment_path
from utils.plots import plot_one_box
from utils.torch_utils import select_device, load_classifier, time_synchronized
import os

ROOT_DIR = os.getcwd()
ROOT_DIR = ROOT_DIR[:-17]

def load_model(weights, device):
    model = attempt_load(weights, map_location=device)  # load FP32 model
    return model


def scale_coords_landmarks(img1_shape, coords, img0_shape, ratio_pad=None):
    # Rescale coords (xyxy) from img1_shape to img0_shape
    if ratio_pad is None:  # calculate from img0_shape
        gain = min(img1_shape[0] / img0_shape[0], img1_shape[1] / img0_shape[1])  # gain  = old / new
        pad = (img1_shape[1] - img0_shape[1] * gain) / 2, (img1_shape[0] - img0_shape[0] * gain) / 2  # wh padding
    else:
        gain = ratio_pad[0][0]
        pad = ratio_pad[1]

    coords[:, [0, 2, 4, 6, 8]] -= pad[0]  # x padding
    coords[:, [1, 3, 5, 7, 9]] -= pad[1]  # y padding
    coords[:, :10] /= gain
    #clip_coords(coords, img0_shape)
    coords[:, 0].clamp_(0, img0_shape[1])  # x1
    coords[:, 1].clamp_(0, img0_shape[0])  # y1
    coords[:, 2].clamp_(0, img0_shape[1])  # x2
    coords[:, 3].clamp_(0, img0_shape[0])  # y2
    coords[:, 4].clamp_(0, img0_shape[1])  # x3
    coords[:, 5].clamp_(0, img0_shape[0])  # y3
    coords[:, 6].clamp_(0, img0_shape[1])  # x4
    coords[:, 7].clamp_(0, img0_shape[0])  # y4
    coords[:, 8].clamp_(0, img0_shape[1])  # x5
    coords[:, 9].clamp_(0, img0_shape[0])  # y5
    return coords

def show_results(img, xywh, conf,landmarks, class_num):
    h,w,c = img.shape
    tl = 1 or round(0.002 * (h + w) / 2) + 1  # line/font thickness
    x1 = int(xywh[0] * w - 0.5 * xywh[2] * w)
    y1 = int(xywh[1] * h - 0.5 * xywh[3] * h)
    x2 = int(xywh[0] * w + 0.5 * xywh[2] * w)
    y2 = int(xywh[1] * h + 0.5 * xywh[3] * h)
    # print("FACE BBOX IS :",x1,x2,y1,y2)
    cv2.rectangle(img, (x1,y1), (x2, y2), (0,255,0), thickness=tl, lineType=cv2.LINE_AA)

    clors = [(255,0,0),(0,255,0),(0,0,255),(255,255,0),(0,255,255)]


    tf = max(tl - 1, 1)  # font thickness
    label = str(conf)[:5]
    cv2.putText(img, label, (x1, y1 - 2), 0, tl / 3, [225, 255, 255], thickness=tf, lineType=cv2.LINE_AA)
    cv2.imshow('result',img)
    cv2.waitKey(5000)
    return img

def save_image(save_path,im_ind, xywh,img):
    
    sha = img.shape
    print("Shape is:", len(sha))
    h = sha[0]
    w = sha[1]
    c = sha[2]
    # img = Image.fromarray(img, 'RGB')
    tl = 1 or round(0.002 * (h + w) / 2) + 1  # line/font thickness
    x1 = int(xywh[0] * w - 0.5 * xywh[2] * w)
    y1 = int(xywh[1] * h - 0.5 * xywh[3] * h)
    x2 = int(xywh[0] * w + 0.5 * xywh[2] * w)
    y2 = int(xywh[1] * h + 0.5 * xywh[3] * h)

    bbox=[min(y1,y2),min(x1,x2),abs(y1-y2),abs(x1-x2)]
    # print("XYWH IS (verify):",xywh)
    # print("X1 X2 Y1 Y2:",x1,x2,y1,y2)
    # print("actual image shape: ",img.shape)

    #crop
    img = img[max(y1-5,0): min(y2+5,h), max(x1-5,0):min(x2+5,w),:]

    # print("cropped image shape: ",img.shape)
    # img= img.crop((x1, y1, x2, y2))

    #write
    put_here=save_path+str(im_ind)+'.jpg'
    print("Path is ", put_here)
    # print("#Saving cropped face ",im_ind," to---",put_here)
    cv2.imwrite(put_here,img)
    # print("IMAGE SAVED")
    return bbox

def detect_one(model, image_path, device):
    # Load model
    img_size = 800
    conf_thres = 0.3
    iou_thres = 0.5

    image_name=image_path.split('/')[-1].split('.')[0]
    # print("#######WORKING ON IMAGE: ",image_name)
    save_path=f'{dir}/data/temp/faces/'+image_name+'_'
    orgimg = cv2.imread(image_path)  # BGR
    img0 = copy.deepcopy(orgimg)
    print("Reached here")
    assert orgimg is not None, 'Image Not Found ' + image_path
    h0, w0 = orgimg.shape[:2]  # orig hw
    r = img_size / max(h0, w0)  # resize image to img_size
    if r != 1:  # always resize down, only resize up if training with augmentation
        interp = cv2.INTER_AREA if r < 1  else cv2.INTER_LINEAR
        img0 = cv2.resize(img0, (int(w0 * r), int(h0 * r)), interpolation=interp)

    imgsz = check_img_size(img_size, s=model.stride.max())  # check img_size

    img = letterbox(img0, new_shape=imgsz)[0]
    # Convert
    img = img[:, :, ::-1].transpose(2, 0, 1).copy()  # BGR to RGB, to 3x416x416

    # Run inference
    t0 = time.time()

    img = torch.from_numpy(img).to(device)
    img = img.float()  # uint8 to fp16/32
    img /= 255.0  # 0 - 255 to 0.0 - 1.0
    if img.ndimension() == 3:
        img = img.unsqueeze(0)

    # Inference
    t1 = time_synchronized()
    pred = model(img)[0]

    # Apply NMS
    pred = non_max_suppression_face(pred, conf_thres, iou_thres)

    # print('img.shape: ', img.shape)
    # print('orgimg.shape: ', orgimg.shape)
    # print("PRED IS :",pred)

    # Process detections
    im_ind=1
    for i, det in enumerate(pred):  # detections per image
        gn = torch.tensor(orgimg.shape)[[1, 0, 1, 0]].to(device)  # normalization gain whwh
        # print("FOR FACE i= ",i," DET= ",det)
        print("NUMBER OF FACES= ",det.size()[0])
        gn_lks = torch.tensor(orgimg.shape)[[1, 0, 1, 0, 1, 0, 1, 0, 1, 0]].to(device)  # normalization gain landmarks
        if len(det):
            # Rescale boxes from img_size to im0 size
            det[:, :4] = scale_coords(img.shape[2:], det[:, :4], orgimg.shape).round()

            # Print results
            for c in det[:, -1].unique():
                n = (det[:, -1] == c).sum()  # detections per class

            det[:, 5:15] = scale_coords_landmarks(img.shape[2:], det[:, 5:15], orgimg.shape).round()

            for j in range(det.size()[0]):
                xywh = (xyxy2xywh(det[j, :4].view(1, 4)) / gn).view(-1).tolist()
                conf = det[j, 4].cpu().numpy()
                landmarks = (det[j, 5:15].view(1, 10) / gn_lks).view(-1).tolist()
                class_num = det[j, 15].cpu().numpy()
                # orgimg = show_results(orgimg, xywh, conf, class_num)
                # print("ORGIMAGE SHAPE: " ,orgimg.shape)
                # print("XYWH IS:",xywh)
                bounder=save_image(save_path,im_ind, xywh,orgimg)
                im_ind+=1
                print(dir)
                fo = open(f'{dir}/output/bbox_file.txt', "a")
                fo.write(str(bounder))
                fo.write('\n')
                fo.close()
                orgimg = show_results(orgimg, xywh, conf, landmarks, class_num)
                save_image(save_path,im_ind, xywh,img)
    cv2.imwrite('result.jpg', orgimg)




if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--weights', nargs='+', type=str, default='runs/train/exp5/weights/last.pt', help='model.pt path(s)')
    parser.add_argument('--image', type=str, default='data/images/test.jpg', help='source')  # file/folder, 0 for webcam
    # parser.add_argument('--image', type=str, default='data/images', help='file/dir/URL/glob, 0 for webcam')
    parser.add_argument('--img-size', type=int, default=640, help='inference size (pixels)')
    opt = parser.parse_args()
    os.getcwd()
    dir = os.getcwd()
    print(opt)
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    print(device)
    model = load_model(opt.weights, device)
    # bbox_wrie_path='/content/drive/MyDrive/Bosch_inter_iit/bbox_file.txt'
    # bbox_file =t open(bbox_write_path,"w+")
    detect_one(model, opt.image, device)
