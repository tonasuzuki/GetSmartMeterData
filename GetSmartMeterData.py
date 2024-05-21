#!/usr/bin/python3
# -*- coding: utf-8 -*-

# Get SmartMeter(Wi-SUN Profile for ECHONET Lite)
#
# 2024/03/03 ver:1.0 tonasuzuki
#
#

#
import requests
import json
import logging
import sys
import serial
import signal
import time
import atexit

##########################
# install python
#  sudo apt install python3 python3-pip
#  sudo pip3 install pyserial
#  sudo pip3 install requests
#

# --------------------------------
# 「電力メーター情報発信サービス(Bルートサービス)」の設定
#
# ----------------
# Bルートサービス 設定情報
B_ROUTE_ID     = '0123456789abcdef0123456789abcdef' # 認証ID
B_ROUTE_PW     = '0123456789ab'                     # パスワード
# ----------------
# シリアルポート設定
SERIAL_PORT  = '/dev/ttyS1'
SERIAL_SPEED = 115200
SERIAL_TIMEOUT = 5
COMMAND_TIMEOUT = 30
# ----------------
# データ取得設定
CONNECT_RETRY_COUNT = 4  #EchoNet機器スキャンリトライ回数
UPDATE_DATA_TIME = 120   #データ取得間隔(秒)
# ----------------
# デバッグログ設定 (実運用時はコメントアウトする)
#logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s:%(name)s - %(message)s")

# ----------------
# HomeAssistantのWebhook URL
HA_URL = 'http://homeassistant.local:8123/api/webhook/echonet-aki-wi-sun'

# ----------設定ここまで ----------


## Wi-SUN Profile Connection Class for ECHONET Lite
#
#
class CommEchoNet:
    __ser = None 
    LocalIPAddr = None 
    dictScanedDesc = {}
 
    def __init__(self):
        self.OpenSerial()

    def __del__(self):
        self.TerminateCommunication()
        self.CloseSerial()

    # シリアルポートを開く
    def OpenSerial(self):
        self.__ser= serial.Serial(SERIAL_PORT, SERIAL_SPEED) # シリアルポートオープン
        self.__ser.timeout = SERIAL_TIMEOUT # シリアル通信のタイムアウトを設定

    # シリアルポートを閉じる
    def CloseSerial(self):
        self.__ser.close()

    #コマンド文字列を送信する
    def SendCommand(self,szCommand,szRawData=None):
        bResult=False 
        if (szRawData is None) :
            szData = str.encode(szCommand + "\r\n")
        else :
            szData = str.encode(szCommand) + szRawData
        self.__ser.write(szData)
        logging.debug(szData)
        bResult=self.__CheckCommandResult()
        return (bResult)

    #結果が(OKの代わりに)戻ってくるコマンドを送信する
    def GetProperty(self,szCommand):
        szResult=''
        logging.debug(szCommand)
        self.__ser.write(str.encode(szCommand + "\r\n"))
        self.__ser.readline()  # Echoback
        szResult=self.__ser.readline().decode(encoding='utf-8')
        return ( szResult.rstrip("\r\n") )

    # ECHOnet Profileの終了コマンドを送信する
    def TerminateCommunication(self):
        logging.info('終了コマンド送信')
        bResult=self.SendCommand("SKTERM")
        nResult=self.__CheckCommandEvent()
        return(nResult)

    # OKがくるまで読み飛ばす
    def __CheckCommandResult(self):
        bConnected = False
        fTimeOut = time.time() + float(COMMAND_TIMEOUT)
        while ((not bConnected) and (fTimeOut > time.time() )) :
            szData = self.__ser.readline().decode(encoding='utf-8')
            logging.debug(szData)
            if szData.startswith("OK") :
                bConnected = True
            if szData.startswith("FAIL") :
                bConnected = True
        return(bConnected) 

    # EVENTがくるまで読み飛ばし、EVENT値を返す
    def __CheckCommandEvent(self):
        nResult= False
        bConnected = False
        fTimeOut = time.time() + float(COMMAND_TIMEOUT)
        while ((not bConnected) and (fTimeOut > time.time() )) :
            szData = self.__ser.readline().decode(encoding='utf-8')
            logging.debug(szData)
            if szData.startswith("EVENT") :
                nResult = int(szData[6:6+2],16)  # 6bytes目から2bytesが結果コード
                bConnected = True
        return(nResult)

    # Bルートサービスの認証ID・パスワードを設定する。
    def SetID(self,szID,szPassword):
        bResult = False 
        # Bルート認証ID設定
        logging.info('Bルート認証ID設定')
        bResult= self.SendCommand("SKSETRBID " + szID)
        if (bResult):
            # Bルート認証パスワード設定
            logging.info('Bルートパスワード設定')
            bResult= self.SendCommand("SKSETPWD C " + szPassword)
        return (bResult)

    # Bルートサービス設定を元に、接続可能なデバイスを探す
    def ScanDevice(self):
        bResult=False
        logging.info('デバイススキャン')
        bResult= self.SendCommand("SKSCAN 2 FFFFFFFF 6 0")
        if (bResult):
            bConnected = False
            bDescription = False
            #デバイススキャン結果を待つ
            while (not bConnected) :
                szData = self.__ser.readline().decode(encoding='utf-8')
                logging.debug(szData)
                if szData.startswith("EVENT 22") :
                    logging.info('アクティブスキャン完了')
                    bConnected = True
                elif szData.startswith("EPANDESC") :
                    #これ以降はEPANDESC結果文字列が届く
                    bDescription = True
                elif (not szData.startswith("EVENT")) :
                    if ":" in szData:
                        # stripで前後の空白を削除
                        self.dictScanedDesc.update(dict([[x.strip() for x in szData.split(":")]])) 
                    else:
                        bDescription = False 
        #デバイスデータが取得できているか確認する。
        strAddr=self.dictScanedDesc.get('Addr')
        if (strAddr is None) :
            bResult=False 
        return (bResult)

    #接続可能なデバイスに接続するためのパラメータ設定を行う
    def SetDeviceParam(self):
        bResult=False
        # Channel設定
        logging.info('Channel設定')
        strChannel=self.dictScanedDesc.get('Channel')
        if (not strChannel is None) :
            bResult= self.SendCommand("SKSREG S2 " + strChannel)
        if (not bResult):
            return(False)
        # PanID設定
        logging.info('PanID設定')
        strPanID=self.dictScanedDesc.get('Pan ID')
        if (not strPanID is None) :
            bResult= self.SendCommand("SKSREG S3 " + strPanID)
        if (not bResult):
            return(False)
        # アドレス変換
        logging.info('MACアドレスをIPv6リンクローカルアドレスに変換')
        self.LocalIPAddr=''
        bResult = False
        strAddr=self.dictScanedDesc.get('Addr')
        if (not strAddr is None) :
            self.LocalIPAddr=self.GetProperty("SKLL64 " + strAddr)
            if (len(self.LocalIPAddr)>0 ) :
                bResult=True
        return (bResult)

    #ECHOnet Liteデバイスに接続する
    def ConnectDevice(self):
        bResult = False
        # PANA接続シーケンスを行う
        logging.info('PANA接続シーケンス')
        if (not self.LocalIPAddr is None) :
            bResult= self.SendCommand("SKJOIN " + self.LocalIPAddr)
        if (bResult):
            # PANA 接続完了を待つ
            bResult = False
            bConnected = False
            fTimeOut = time.time() + float(COMMAND_TIMEOUT)
            while ((not bConnected) and (fTimeOut > time.time() )) :
                szData = self.__ser.readline().decode(encoding='utf-8')
                logging.debug(szData)
                if szData.startswith("EVENT 24") :
                    logging.info('PANA 接続失敗')
                    bConnected = True
                elif szData.startswith("EVENT 25") :
                    logging.info('PANA 接続成功')
                    bConnected = True
                    bResult = True
        #EVENT 25の後にERXUDPが届くので取得のみ行う
        szData = self.__ser.readline().decode(encoding='utf-8')
        return (bResult)

    #ECHOnet liteコマンドを送信し、結果を返す
    def SendEchonetCommand(self,szEPC):
        nResult=0
        logging.info('EchoNetデータ取得')
        # 瞬時電力計測値取得コマンドフレーム
        szEchonetCommandHeader = b'\x10\x81\x00\x01\x05\xFF\x01\x02\x88\x01\x62\x01'
        szEchonetCommand = szEchonetCommandHeader + szEPC + b'\00'
        szCommand = "SKSENDTO 1 {0} 0E1A 1 0 {1:04X} ".format(self.LocalIPAddr, len(szEchonetCommand))
        bResult= self.SendCommand(szCommand , szEchonetCommand)
        bConnected = False
        fTimeOut = time.time() + float(COMMAND_TIMEOUT)
        while ((not bConnected) and (fTimeOut > time.time() )) :
            # 返信データ取得
            szData = self.__ser.readline().decode(encoding='utf-8')
            logging.debug(szData)
            # 結果データを得る
            if szData.startswith("ERXUDP"):
                ResultCols = szData.strip().split(' ')  #結果をスペースごとに分ける
                szEData = ResultCols[9]  # 9個目が結果データ(EData)
                seoj = szEData[ 8:8 +6]  # 8bytes目から6bytesがSEOJ(送信元ECHONET Liteオブジェクト) 
                deoj = szEData[14:14+6]  # 14bytes目から6bytesがDEOJ(受信先ECHONET Liteオブジェクト) 
                esv  = szEData[20:20+2]  # 20bytes目から2bytesがESV(ECHONET Liteサービス結果)
                epc  = szEData[24:24+2]  # 24bytes目から2bytesがEPC(ECHONET Liteプロパティ)
                pdc  = int(szEData[26:26+2],16)  # 26bytes目から2bytesがPDC(EDTのバイト数)
                # 正常結果か?
                if ((esv == "72") and (pdc>0)) :
                    # 結果を取得する
                    nResult = int(szEData[28:28+(pdc*2)],16)  # 86bytes目からPDCバイトがEDT(結果の数値)
                    bConnected = True
        return(nResult)


    # 初期化。最初の一度だけ実行する。
    def InitConnection(self):
        #Send ID/PASSWORD
        bResult=self.SetID(B_ROUTE_ID,B_ROUTE_PW)
        if (not bResult) :
            return(False) 
        #
        bResult=False
        nRetry=CONNECT_RETRY_COUNT
        while ((not bResult) and (nRetry>0)) :
            bResult=self.ScanDevice()
            nRetry-=1
        if (not bResult) :
            logging.info('ECHONetデバイスが見つかりません')
            return(False) 
        # Set TagetDevice Parameter
        bResult=self.SetDeviceParam()
        if (not bResult) :
            logging.info('接続先を設定できませんでした')
            return(False) 
        # Connect TargetDevice
        bResult=self.ConnectDevice()
        if (not bResult) :
            logging.info('接続先に接続できませんでした')
            return(False) 
        return (True)

    #瞬時電力計測値を取得する
    def GetMeasuredPower(self):
        szEPC = b'\xE7'
        nResult=self.SendEchonetCommand(szEPC)
        return(nResult)

    #積算電力量 計測値 を取得する
    def GetIntegratedpower(self):
        #積算電力量の単位テーブル
        dictUnit = {0:1,1:0.1,2:0.01,3:0.001,4:0.0001,10:10,11:100,12:1000,13:10000}
        #積算電力量の単位を取得する
        szEPC = b'\xE1'
        nUnitTable=self.SendEchonetCommand(szEPC)
        fUnit=float(dictUnit.get(nUnitTable, 1))
        #積算電力量計測値を取得する
        szEPC = b'\xE0'
        nResult=self.SendEchonetCommand(szEPC)
        #積算電力量計測値を算出する
        fResult=float(nResult)*fUnit
        return(fResult)
#class CommEchoNet

class AkiboxLed:
    def __init__(self):
        self.clear()

    def __led(self,nLedNumber,nLedCmd):
        if ((nLedNumber>=1) and (nLedNumber<=4) ) :
            szDir = '/sys/class/leds/led{0:1d}/brightness'.format(nLedNumber)
            if (nLedCmd==0) :
                szCmd = '0'
            else:
                szCmd = '1'
            fDev = open(szDir, "w")
            fDev.write(szCmd)
            fDev.close()
    
    def clear(self):
        nLedNumber=4
        while (nLedNumber>0) :
            self.__led(nLedNumber,0)
            nLedNumber-=1
    
    # Aki-boxのLEDを点灯する(nLedNumberは 1～4)
    def on(self,nLedNumber):
        self.__led(nLedNumber,1)

    # Aki-boxのLEDを消灯する(nLedNumberは 1～4)    
    def off(self,nLedNumber):
        self.__led(nLedNumber,0)

#class AkiboxLed:


#######################################################################
# Global Functions


## main loop
echonet=CommEchoNet()
boxled=AkiboxLed()

def main(arg1, arg2):
    # Get Power-data from EchoNet
    boxled.on(3)
    boxled.on(4)
    nMeasuredPower=echonet.GetMeasuredPower()
    logging.info(u"瞬時電力計測値:{0}[W]".format(nMeasuredPower))
    fIntegratedpower=echonet.GetIntegratedpower()
    logging.info(u"積算電力量計測値:{0}[KW]".format(fIntegratedpower))
    boxled.off(4)
    # 2データとも取得できているときのみPOST HomeAssistant
    if nMeasuredPower > 0 and fIntegratedpower > 0: 
        try:
            response = requests.post(
                HA_URL,
                json={'measuredpower': nMeasuredPower, 'integratedpower': fIntegratedpower},
                headers={"Content-Type": "application/json"}
            )
        except Exception as e:
            logging.info('ERROR: Post webhook')
            boxled.off(3)

def _atexit():
    boxled.clear()

## Python Signal Handler 
if __name__ == '__main__':
    # 終了ハンドラに登録する
    atexit.register(_atexit)
    if (echonet.InitConnection()):
        boxled.on(2)
        # 起動して5秒目から、UPDATE_DATA_TIME秒ごとにmain関数を実行する。
        signal.signal(signal.SIGALRM, main)
        signal.setitimer(signal.ITIMER_REAL, 5, UPDATE_DATA_TIME)
        while True:
            time.sleep(100)
    else :
        logging.info('ECHONetデバイスと接続できませんでした.')
        sys.exit() #接続失敗した時は終了
