import os
import wincertstore

# pip install wincertstore
# cert-utils.py
# This script is designed to export trusted intermediate certificates 
# from the Windows certificate repository into PEM format files.
# The script exports trusted roots and intermediate CA certificates from Windows certificate store
# to PEM format files for use in other systems/protocols that require
# certificate chain validation.

def export_windows_certs_to_pem(output_file="cert.pem"):
    """
    Exports all certificates from the Windows 'ROOT' (trusted roots) and 'CA' (intermediate CAs)
    stores to a single PEM file.
    
    This function is specifically designed to export trusted roots and intermediate CA
    certificates from the Windows certificate repository into PEM format, which is commonly
    used in SSL/TLS implementations and other security protocols.
    
    The function:
    1. Checks if the operating system is Windows
    2. Defines the certificate stores to check (ROOT and CA)
    3. Iterates through each store and exports all certificates
    4. Writes the certificates to a PEM file
    5. Provides output about the export process
    
    Parameters:
    output_file (str): The filename to save the PEM certificates to (default: cert.pem)
    """
    if os.name != 'nt':
        print("This script is intended for Windows only.")
        return

    # Define the certificate stores to check:
    # - ROOT store contains trusted root certificates
    # - CA store contains intermediate CA certificates
    # These stores contain the certificates that need to be exported
    store_names = ["ROOT", "CA"]
    cert_count = 0  # Counter for successfully exported certificates

    with open(output_file, 'w', encoding='utf-8') as pem_file:
        for store_name in store_names:
            try:
                with wincertstore.CertSystemStore(store_name) as store:
                    for cert in store.itercerts(usage=wincertstore.SERVER_AUTH):
                        try:
                            # Convert certificate to PEM format
                            # wincertstore.get_pem() returns a PEM encoded string
                            pem_data = cert.get_pem()
                            if pem_data:
                                # Write the PEM data to the output file
                                pem_file.write(pem_data)
                                cert_count += 1  # Increment the certificate counter
                        except Exception as e:
                            print(f"Error processing a certificate in {store_name} store: {e}")
            except Exception as e:
                print(f"Error accessing the {store_name} store: {e}")

    # Output summary of the export results
    print(f"Exported {cert_count} certificates to {output_file}")
    print(f"The file can be found at: {os.path.abspath(output_file)}")
    print("This PEM file can be used for SSL/TLS configurations and certificate chain validation")
    print("in various applications and services that require trusted certificate authorities.")


if __name__ == "__main__":
    export_windows_certs_to_pem()
