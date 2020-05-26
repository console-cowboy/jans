import os
import glob
import shutil

from setup_app import paths
from setup_app.config import Config
from setup_app.installers.jetty import JettyInstaller

class SamlInstaller(JettyInstaller):

    def __init__(self):
        self.service_name = 'idp'
        self.pbar_text = "Installing Saml"
        self.idp3_war = 'https://ox.gluu.org/maven/org/gluu/oxshibbolethIdp/%s/oxshibbolethIdp-%s.war' % (Config.oxVersion, Config.oxVersion)
        self.idp3_dist_jar = 'https://ox.gluu.org/maven/org/gluu/oxShibbolethStatic/%s/oxShibbolethStatic-%s.jar' % (Config.oxVersion, Config.oxVersion)
        self.idp3_cml_keygenerator = 'https://ox.gluu.org/maven/org/gluu/oxShibbolethKeyGenerator/%s/oxShibbolethKeyGenerator-%s.jar' % (Config.oxVersion, Config.oxVersion)

    def install(self):
        self.logIt("Install SAML Shibboleth IDP v3...")

        # Put latest SAML templates
        identityWar = 'identity.war'

        # unpack IDP3 JAR with static configs
        self.run([Config.cmd_jar, 'xf', os.path.join(Config.distGluuFolder, 'shibboleth-idp.jar')], '/opt')
        self.removeDirs('/opt/META-INF')

        if Config.mappingLocations['user'] == 'couchbase':
            self.templateRenderingDict['idp_attribute_resolver_ldap.search_filter'] = '(&(|(lower(uid)=$requestContext.principalName)(mail=$requestContext.principalName))(objectClass=gluuPerson))'

        # Process templates
        self.renderTemplateInOut(Config.idp3_configuration_properties, Config.staticIDP3FolderConf, Config.idp3ConfFolder)
        self.renderTemplateInOut(Config.idp3_configuration_ldap_properties, Config.staticIDP3FolderConf, Config.idp3ConfFolder)
        self.renderTemplateInOut(Config.idp3_configuration_saml_nameid, Config.staticIDP3FolderConf, Config.idp3ConfFolder)
        self.renderTemplateInOut(Config.idp3_configuration_services, Config.staticIDP3FolderConf, Config.idp3ConfFolder)
        self.renderTemplateInOut(
                        Config.idp3_configuration_password_authn, 
                        os.path.join(Config.staticIDP3FolderConf, 'authn'),
                        os.path.join(Config.idp3ConfFolder, 'authn')
                        )

        # load certificates to update metadata
        Config.templateRenderingDict['idp3EncryptionCertificateText'] = self.load_certificate_text(os.path.join(Config.certFolder, 'idp-encryption.crt'))
        Config.templateRenderingDict['idp3SigningCertificateText'] = self.load_certificate_text(os.path.join(Config.certFolder, 'idp-signing.crt'))
        # update IDP3 metadata
        self.renderTemplateInOut(Config.idp3_metadata, Config.staticIDP3FolderMetadata, Config.idp3MetadataFolder)

        self.installJettyService(Config.jetty_app_configuration[self.service_name], True)
        jettyServiceWebapps = os.path.join(Config.jetty_base, self.service_name,  'webapps')
        src_war = os.path.join(Config.distGluuFolder, 'idp.war')
        self.copyFile(src_war, jettyServiceWebapps)

        # Prepare libraries needed to for command line IDP3 utilities
        self.install_saml_libraries()

        # generate new keystore with AES symmetric key
        # there is one throuble with Shibboleth IDP 3.x - it doesn't load keystore from /etc/certs. It accepts %{idp.home}/credentials/sealer.jks  %{idp.home}/credentials/sealer.kver path format only.
        cmd = [Config.cmd_java,'-classpath', '"{}"'.format(os.path.join(Config.idp3Folder,'webapp/WEB-INF/lib/*')),
                'net.shibboleth.utilities.java.support.security.BasicKeystoreKeyStrategyTool',
                '--storefile', os.path.join(Config.idp3Folder,'credentials/sealer.jks'),
                '--versionfile',  os.path.join(Config.idp3Folder, 'credentials/sealer.kver'),
                '--alias secret',
                '--storepass', Config.shibJksPass]
            
        self.run(' '.join(cmd), shell=True)

        # chown -R jetty:jetty /opt/shibboleth-idp
        # self.run([self.cmd_chown,'-R', 'jetty:jetty', self.idp3Folder], '/opt')
        self.run([paths.cmd_chown, '-R', 'jetty:jetty', jettyServiceWebapps], '/opt')


        if Config.persistence_type == 'couchbase':
            Config.saml_couchbase_settings()
        elif Config.persistence_type == 'hybrid':
            couchbase_mappings = Config.getMappingType('couchbase')
            if 'user' in couchbase_mappings:
                self.saml_couchbase_settings()

        self.enable()

    def install_saml_libraries(self):
        # Unpack oxauth.war to get bcprov-jdk16.jar
        idpWar = 'idp.war'
        distIdpPath = os.path.join(Config.distGluuFolder, 'idp.war')

        tmpIdpDir = os.path.join(Config.distFolder, 'tmp/tmp_idp')

        self.logIt("Unpacking %s..." % idpWar)
        self.removeDirs(tmpIdpDir)
        self.createDirs(tmpIdpDir)

        self.run([Config.cmd_jar, 'xf', distIdpPath], tmpIdpDir)

        # Copy libraries into webapp
        idp3WebappLibFolder = os.path.join(Config.idp3WebappFolder, 'WEB-INF/lib')
        self.createDirs(idp3WebappLibFolder)
        self.copyTree(os.path.join(tmpIdpDir, 'WEB-INF/lib'), idp3WebappLibFolder)

        self.removeDirs(tmpIdpDir)


    def saml_couchbase_settings(self):
        # Add couchbase bean to global.xml
        couchbase_bean_xml_fn = os.path.join(Config.staticFolder, 'couchbase/couchbase_bean.xml')
        global_xml_fn = os.path.join(Config.idp3ConfFolder, 'global.xml')
        couchbase_bean_xml = self.readFile(couchbase_bean_xml_fn)
        global_xml = self.readFile(global_xml_fn)
        global_xml = global_xml.replace('</beans>', couchbase_bean_xml+'\n\n</beans>')
        self.writeFile(global_xml_fn, global_xml)

        # Add datasource.properties to idp.properties
        idp3_configuration_properties_fn = os.path.join(Config.idp3ConfFolder, Config.idp3_configuration_properties)

        with open(idp3_configuration_properties_fn) as f:
            idp3_properties = f.readlines()

        for i,l in enumerate(idp3_properties[:]):
            if l.strip().startswith('idp.additionalProperties'):
                idp3_properties[i] = l.strip() + ', /conf/datasource.properties\n'

        new_idp3_props = ''.join(idp3_properties)
        self.writeFile(idp3_configuration_properties_fn, new_idp3_props)

        data_source_properties = os.path.join(Config.outputFolder, Config.data_source_properties)

        self.copyFile(data_source_properties, Config.idp3ConfFolder)

    def create_folders(self):
        self.createDirs(os.path.join(Config.gluuBaseFolder, 'conf/shibboleth3'))
        self.createDirs(os.path.join(Config.jetty_base, 'identity/conf/shibboleth3/idp'))
        self.createDirs(os.path.join(Config.jetty_base, 'identity/conf/shibboleth3/sp'))
        
        for folder in (Config.idp3Folder, Config.idp3MetadataFolder, Config.idp3MetadataCredentialsFolder,
                        Config.idp3LogsFolder, Config.idp3LibFolder, Config.idp3ConfFolder, 
                        Config.idp3ConfAuthnFolder, Config.idp3CredentialsFolder, Config.idp3WebappFolder):
            
            self.run([paths.cmd_mkdir, '-p', folder])

        self.run([paths.cmd_chown, '-R', 'jetty:jetty', Config.idp3Folder])

    def download_files(self):
        Config.pbar.progress('saml', "Downloading Shibboleth IDP v3 war file", False)
        self.run([paths.cmd_wget, self.idp3_war, '--no-verbose', '-c', '--retry-connrefused', '--tries=10', '-O', os.path.join(Config.distGluuFolder, 'idp.war')])
        Config.pbar.progress('saml', "Downloading Shibboleth IDP v3 keygenerator", False)
        self.run([paths.cmd_wget, self.idp3_cml_keygenerator, '--no-verbose', '-c', '--retry-connrefused', '--tries=10', '-O', os.path.join(Config.distGluuFolder, 'idp3_cml_keygenerator.jar')])
        Config.pbar.progress('saml', "Downloading Shibboleth IDP v3 binary distributive file", False)
        self.run([paths.cmd_wget, self.idp3_dist_jar, '--no-verbose', '-c', '--retry-connrefused', '--tries=10', '-O', os.path.join(Config.distGluuFolder, 'shibboleth-idp.jar')])
