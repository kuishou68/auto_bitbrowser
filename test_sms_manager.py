import asyncio
import argparse
import sys
from sms_manager import SMSManager, ProviderType, SMSException, RentStatus

async def main():
    parser = argparse.ArgumentParser(description="Test SMS Manager Module")
    parser.add_argument("--provider", type=str, choices=["sms-man", "5sim", "vak-sms"], required=True, help="SMS Provider (sms-man, 5sim, vak-sms)")
    parser.add_argument("--key", type=str, required=True, help="API Key")
    parser.add_argument("--country", type=str, default="us", help="Country code (e.g., us, ru)")
    parser.add_argument("--service", type=str, default="tg", help="Service code (e.g., tg, go)")
    parser.add_argument("--action", type=str, choices=["balance", "rent"], default="balance", help="Action to perform")
    
    args = parser.parse_args()

    # Map string to Enum
    provider_map = {
        "sms-man": ProviderType.SMS_MAN,
        "5sim": ProviderType.FIVE_SIM,
        "vak-sms": ProviderType.VAK_SMS
    }
    
    provider_type = provider_map[args.provider]
    manager = SMSManager(provider_type, args.key)

    try:
        print(f"[*] Initializing {args.provider}...")
        
        # 1. Check Balance
        balance = await manager.get_balance()
        print(f"[*] Current Balance: {balance}")
        
        if args.action == "rent":
            print(f"[*] Attempting to rent number for {args.service} in {args.country}...")
            order = await manager.rent_number(args.country, args.service)
            print(f"[+] Rent Successful!")
            print(f"    Order ID: {order.order_id}")
            print(f"    Phone: {order.phone_number}")
            print(f"    Link: {manager.provider.base_url}")
            
            print("[*] Waiting for SMS code (Ctrl+C to cancel)...")
            try:
                # Wait for 2 minutes for testing
                order = await manager.wait_for_code(order, timeout_seconds=120)
                
                if order.status == RentStatus.RECEIVED:
                    print(f"\n[SUCCESS] SMS Code Received: {order.sms_code}")
                    print(f"Full Message: {order.sms_text}")
                else:
                    print(f"\n[TIMEOUT] Status: {order.status.value}")
                    
            except KeyboardInterrupt:
                print("\n[*] Cancelling rent...")
                # Try to cancel
                await manager.provider.cancel_rent(order.order_id)
                print("[*] Cancelled.")
                
    except SMSException as e:
        print(f"[ERROR] SMS API Error: {str(e)}")
    except Exception as e:
        print(f"[ERROR] Unexpected Error: {str(e)}")

if __name__ == "__main__":
    if sys.platform == 'win32':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(main())
