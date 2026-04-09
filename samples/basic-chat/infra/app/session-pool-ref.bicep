@description('Name of the ACA session pool to reference.')
param sessionPoolName string

resource sessionPool 'Microsoft.App/sessionPools@2025-01-01' existing = {
  name: sessionPoolName
}

output location string = sessionPool.location
output poolManagementEndpoint string = sessionPool.properties.poolManagementEndpoint
